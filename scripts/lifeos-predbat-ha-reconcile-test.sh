#!/usr/bin/env bash
set -Eeuo pipefail
echo PRED_RECONCILE_STAGE=restart_homeassistant
docker restart homeassistant >/dev/null
echo PRED_RECONCILE_STAGE=wait_homeassistant
for _ in $(seq 1 60); do
  running=$(docker inspect -f '{{.State.Running}}' homeassistant 2>/dev/null || true)
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' homeassistant 2>/dev/null || true)
  if [[ "$running" == true && "$health" != starting ]]; then break; fi
  sleep 2
done
test "$(docker inspect -f '{{.State.Running}}' homeassistant)" = true
echo HOMEASSISTANT_RUNNING=PASS
echo HOMEASSISTANT_HEALTH="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' homeassistant)"
echo PREDBAT_IMAGE="$(docker inspect -f '{{.Image}}' predbat)"
echo PRED_RECONCILE_RESULT=PASS
