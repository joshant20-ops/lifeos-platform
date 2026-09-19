#!/usr/bin/env bash
set -Eeuo pipefail
compose=/opt/stacks/predbat/docker-compose.yml
sanity=/opt/stacks/lifeos-energy/predbat-sanity/collector.py
old=$(docker inspect -f '{{.Image}}' predbat); test -n "$old"
candidate=$(docker image inspect nipar44/predbat_addon:latest -f '{{.Id}}'); test -n "$candidate"
test "$candidate" != "$old"
tmp=$(mktemp); cp "$compose" "$tmp"
rollback(){ cp "$tmp" "$compose"; docker image tag "$old" nipar44/predbat_addon:lifeos-rollback >/dev/null; sed -i 's#image: .*#image: nipar44/predbat_addon:lifeos-rollback#' "$compose"; docker compose -f "$compose" up -d --no-deps --force-recreate predbat >/dev/null; test "$(docker inspect -f '{{.Image}}' predbat)" = "$old"; cp "$tmp" "$compose"; }
trap 'rc=$?; if [ $rc -ne 0 ]; then rollback || true; fi; rm -f "$tmp"; exit $rc' EXIT
docker image tag "$candidate" nipar44/predbat_addon:lifeos-candidate >/dev/null
sed -i 's#image: .*#image: nipar44/predbat_addon:lifeos-candidate#' "$compose"
docker compose -f "$compose" up -d --no-deps --force-recreate predbat >/dev/null
sleep 30
test "$(docker inspect -f '{{.State.Running}}' predbat)" = true
test "$(docker inspect -f '{{.Image}}' predbat)" = "$candidate"
python3 "$sanity" >/dev/null
python3 - <<'PY'
import json
p="/opt/stacks/lifeos-energy/predbat-sanity-export/latest.json"
d=json.load(open(p))
assert not d.get("anomaly_flags"), "sanity regression"
PY
cp "$tmp" "$compose"; trap - EXIT; rm -f "$tmp"
echo MANAGED_UPDATE_REGRESSION=PASS
echo MANAGED_UPDATE_APPLY=PASS
