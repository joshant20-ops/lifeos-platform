#!/usr/bin/env bash
set -Eeuo pipefail
stage=init
trap 'rc=$?; echo "MANAGED_UPDATE_ERROR_STAGE=$stage" >&2; echo "MANAGED_UPDATE_ERROR_LINE=$LINENO" >&2; echo "MANAGED_UPDATE_ERROR_RC=$rc" >&2' ERR
compose=/opt/stacks/predbat/docker-compose.yml
sanity=/opt/stacks/lifeos-energy/predbat-sanity/collector.py
sanity_export=/opt/stacks/lifeos-energy/predbat-sanity-export/latest.json
stage=inspect-current
echo MANAGED_UPDATE_STAGE=$stage
old=$(docker inspect -f '{{.Image}}' predbat); test -n "$old"
stage=inspect-candidate
echo MANAGED_UPDATE_STAGE=$stage
candidate=$(docker image inspect nipar44/predbat_addon:latest -f '{{.Id}}'); test -n "$candidate"
stage=compare-images
echo MANAGED_UPDATE_STAGE=$stage
test "$candidate" != "$old"
stage=backup-compose
echo MANAGED_UPDATE_STAGE=$stage
tmp=$(mktemp); cp "$compose" "$tmp"
rollback(){ stage=rollback; echo MANAGED_UPDATE_STAGE=$stage; cp "$tmp" "$compose"; docker image tag "$old" nipar44/predbat_addon:lifeos-rollback >/dev/null; sed -i 's#image: .*#image: nipar44/predbat_addon:lifeos-rollback#' "$compose"; docker compose -f "$compose" up -d --no-deps --force-recreate predbat; test "$(docker inspect -f '{{.Image}}' predbat)" = "$old"; cp "$tmp" "$compose"; }
trap 'rc=$?; if [ $rc -ne 0 ]; then rollback || true; fi; rm -f "$tmp"; exit $rc' EXIT
stage=tag-candidate
echo MANAGED_UPDATE_STAGE=$stage
docker image tag "$candidate" nipar44/predbat_addon:lifeos-candidate >/dev/null
stage=pin-compose
echo MANAGED_UPDATE_STAGE=$stage
sed -i 's#image: .*#image: nipar44/predbat_addon:lifeos-candidate#' "$compose"
stage=recreate-candidate
echo MANAGED_UPDATE_STAGE=$stage
docker compose -f "$compose" up -d --no-deps --force-recreate predbat >/dev/null
stage=verify-running
echo MANAGED_UPDATE_STAGE=$stage
test "$(docker inspect -f '{{.State.Running}}' predbat)" = true
stage=verify-image
echo MANAGED_UPDATE_STAGE=$stage
test "$(docker inspect -f '{{.Image}}' predbat)" = "$candidate"
stage=update-predbat-core
echo MANAGED_UPDATE_STAGE=$stage
candidate_version=$(docker image inspect nipar44/predbat_addon:latest -f '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || true)
candidate_version="${candidate_version#v}"
test -n "$candidate_version"
# /config is persistent, so replacing the Docker image does not replace Predbat core.
# Use Predbat's checksum-verified updater for the accepted release.
docker exec predbat sh -lc "cd /config/apps/predbat && python3 download.py --download v$candidate_version"
docker restart predbat >/dev/null
for _ in $(seq 1 60); do
  test "$(docker inspect -f '{{.State.Running}}' predbat 2>/dev/null || true)" = true && break
  sleep 2
done
test "$(docker inspect -f '{{.State.Running}}' predbat)" = true
stage=verify-predbat-core
echo MANAGED_UPDATE_STAGE=$stage
core_version=$(docker exec predbat sh -lc "cd /config/apps/predbat && python3 -c 'import predbat; print(predbat.THIS_VERSION)'" | tail -1)
core_version="${core_version#v}"
echo MANAGED_UPDATE_CORE_VERSION="$core_version"
test "$core_version" = "$candidate_version"
echo MANAGED_UPDATE_CORE=PASS
stage=sanity-service-discovery
echo MANAGED_UPDATE_STAGE=$stage
mapfile -t sanity_units < <(
  systemctl list-unit-files --type=service --no-legend |
  awk '{print $1}' |
  while read -r unit; do
    systemctl show -p ExecStart --value "$unit" 2>/dev/null | grep -Fq "$sanity" && echo "$unit" || true
  done
)
test "${#sanity_units[@]}" -eq 1
sanity_unit="${sanity_units[0]}"
echo MANAGED_UPDATE_SANITY_UNIT="$sanity_unit"

# Predbat publishes its HA forecast asynchronously after container startup.
# Require the real secret-aware sanity service to prove readiness; never
# convert a transient restart state into either acceptance or immediate
# rollback. Five minutes is bounded and remains fail-closed.
stage=readiness
echo MANAGED_UPDATE_STAGE=$stage
ready=false
for attempt in $(seq 1 10); do
  before_mtime=$(stat -c %Y "$sanity_export" 2>/dev/null || echo 0)
  systemctl start "$sanity_unit"
  after_mtime="$before_mtime"
  for _ in $(seq 1 15); do
    after_mtime=$(stat -c %Y "$sanity_export" 2>/dev/null || echo 0)
    [ "$after_mtime" -gt "$before_mtime" ] && break
    sleep 1
  done
  test "$after_mtime" -gt "$before_mtime"

  if python3 - "$sanity_export" "$attempt" <<'PY'
import json,sys
p,attempt=sys.argv[1:]
d=json.load(open(p))
a=d.get("sanity_assessment") or {}
flags=list(d.get("anomaly_flags") or [])
fails=list(a.get("fail_flags") or [])
watches=list(a.get("watch_flags") or [])
print("MANAGED_UPDATE_SANITY_ATTEMPT="+attempt)
print("MANAGED_UPDATE_SANITY_LEVEL="+str(a.get("level","UNKNOWN")))
print("MANAGED_UPDATE_SANITY_FAIL_FLAGS="+(",".join(fails) if fails else "none"))
print("MANAGED_UPDATE_SANITY_WATCH_FLAGS="+(",".join(watches) if watches else "none"))
# WATCH is safe enough to continue: the collector explicitly defines it as
# trustworthy data with an economic-strategy advisory. FAIL remains blocking.
raise SystemExit(0 if a.get("level") in {"PASS","WATCH"} and not fails else 1)
PY
  then
    ready=true
    break
  fi
  sleep 15
done
test "$ready" = true
stage=sanity-evaluate
echo MANAGED_UPDATE_STAGE=$stage
python3 - "$sanity_export" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
a=d.get("sanity_assessment") or {}
assert a.get("level") in {"PASS","WATCH"}, "sanity did not reach trustworthy state"
assert not a.get("fail_flags"), "sanity has blocking fail flags"
PY
stage=accept-candidate
echo MANAGED_UPDATE_STAGE=$stage
candidate_digest="${candidate#sha256:}"
sed -i "s#image: .*#image: nipar44/predbat_addon@sha256:$candidate_digest#" "$compose"
# The running container was created from the temporary local tag. Recreate
# once from the immutable accepted reference so runtime and compose agree.
docker compose -f "$compose" up -d --no-deps --force-recreate predbat >/dev/null
test "$(docker inspect -f '{{.Image}}' predbat)" = "$candidate"
trap - EXIT ERR
rm -f "$tmp"
echo MANAGED_UPDATE_ACCEPTED_DIGEST="sha256:$candidate_digest"
echo MANAGED_UPDATE_REGRESSION=PASS
echo MANAGED_UPDATE_APPLY=PASS
