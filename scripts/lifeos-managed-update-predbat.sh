#!/usr/bin/env bash
set -Eeuo pipefail
STACK=/opt/stacks/predbat
COMPOSE="$STACK/docker-compose.yml"
SANITY=/opt/stacks/lifeos-energy/predbat-sanity/collector.py
TARGET_IMAGE="nipar44/predbat_addon:latest"
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
before="$work/before.yml"; cp "$COMPOSE" "$before"
before_id=$(docker inspect -f '{{.Image}}' predbat 2>/dev/null || true)
test -n "$before_id"
echo PREDBAT_UPDATE_PREFLIGHT=PASS
echo PREDBAT_ROLLBACK_IMAGE_CAPTURED=PASS
# Existing config volume is preserved; compose definition is copied for exact restore.
docker pull "$TARGET_IMAGE" >/dev/null
candidate=$(docker image inspect "$TARGET_IMAGE" -f '{{.Id}}')
test -n "$candidate"
if [ "$candidate" = "$before_id" ]; then
  echo PREDBAT_UPDATE_ALREADY_CURRENT=PASS
  exit 0
fi
rollback(){
  echo PREDBAT_UPDATE_ROLLBACK=START
  cp "$before" "$COMPOSE"
  docker image tag "$before_id" nipar44/predbat_addon:lifeos-rollback
  sed -i 's#image: .*#image: nipar44/predbat_addon:lifeos-rollback#' "$COMPOSE"
  docker compose -f "$COMPOSE" up -d --no-deps --force-recreate predbat >/dev/null
  sleep 20
  docker inspect -f '{{.State.Running}}' predbat | grep -qx true
  echo PREDBAT_UPDATE_ROLLBACK=PASS
}
trap 'rc=$?; if [ $rc -ne 0 ]; then rollback || true; fi; exit $rc' ERR
docker compose -f "$COMPOSE" up -d --no-deps --force-recreate predbat >/dev/null
sleep 30
docker inspect -f '{{.State.Running}}' predbat | grep -qx true
# Existing specialist verifier is authoritative for energy-path regression.
python3 "$SANITY" >/dev/null
latest=/opt/stacks/lifeos-energy/predbat-sanity-export/latest.json
test -s "$latest"
python3 - "$latest" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
flags=d.get("anomaly_flags",[])
if flags: raise SystemExit("predbat sanity anomalies present")
PY
# Preserve desired immutable candidate identity for audit.
echo "PREDBAT_BEFORE_IMAGE=$before_id"
echo "PREDBAT_CANDIDATE_IMAGE=$candidate"
echo PREDBAT_SANITY_REGRESSION=PASS
echo PREDBAT_UPDATE_RESULT=PASS
