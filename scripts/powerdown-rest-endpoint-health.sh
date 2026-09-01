#!/usr/bin/env bash
set -Eeuo pipefail
START=$(date +%s)
e(){ local d=$(( $(date +%s)-START )); printf '[%dm%02ds]' $((d/60)) $((d%60)); }
echo '===== POWER DOWN REST ENDPOINT HEALTH ====='
echo 'Expected: <15 sec'
date --iso-8601=seconds

echo
 echo '===== 1/4 — HOST ENDPOINT ====='
set +e
curl -sS --max-time 5 -w '\nHTTP_CODE=%{http_code}\nTOTAL_TIME=%{time_total}\n' http://127.0.0.1:8110/api/energy/current
rc=$?
set -e
echo "CURL_RC=$rc"

echo
 echo '===== 2/4 — LIFEOS-ENERGY CONTAINER ====='
docker inspect lifeos-energy --format 'STATUS={{.State.Status}} HEALTH={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} STARTED={{.State.StartedAt}} RESTARTS={{.RestartCount}}' 2>/dev/null || true
docker logs --since 3h --tail 120 lifeos-energy 2>&1 | grep -Ei 'error|exception|traceback|energy/current|8110|timeout|failed' | tail -80 || true

echo
 echo '===== 3/4 — HOME ASSISTANT REST ERRORS ====='
docker logs --since 3h --tail 500 homeassistant 2>&1 | grep -Ei 'rest|8110|lifeos.energy|energy/current|timeout|client.*error|connection' | tail -120 || true

echo
 echo '===== 4/4 — LISTENER ====='
ss -ltnp | grep ':8110' || true

echo "$(e) REST_ENDPOINT_TRACE=PASS"
