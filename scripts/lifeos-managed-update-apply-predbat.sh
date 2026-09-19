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
stage=settle
echo MANAGED_UPDATE_STAGE=$stage
sleep 30
stage=verify-running
echo MANAGED_UPDATE_STAGE=$stage
test "$(docker inspect -f '{{.State.Running}}' predbat)" = true
stage=verify-image
echo MANAGED_UPDATE_STAGE=$stage
test "$(docker inspect -f '{{.Image}}' predbat)" = "$candidate"
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
before_mtime=$(stat -c %Y "$sanity_export" 2>/dev/null || echo 0)
stage=sanity-collector
echo MANAGED_UPDATE_STAGE=$stage
systemctl start "$sanity_unit"
for _ in $(seq 1 30); do
  after_mtime=$(stat -c %Y "$sanity_export" 2>/dev/null || echo 0)
  if [ "$after_mtime" -gt "$before_mtime" ]; then break; fi
  sleep 1
done
test "${after_mtime:-0}" -gt "$before_mtime"
stage=sanity-evaluate
echo MANAGED_UPDATE_STAGE=$stage
python3 - <<'PY'
import json
p="/opt/stacks/lifeos-energy/predbat-sanity-export/latest.json"
d=json.load(open(p))
assert not d.get("anomaly_flags"), "sanity regression"
PY
stage=restore-compose
echo MANAGED_UPDATE_STAGE=$stage
cp "$tmp" "$compose"; trap - EXIT ERR; rm -f "$tmp"
echo MANAGED_UPDATE_REGRESSION=PASS
echo MANAGED_UPDATE_APPLY=PASS
