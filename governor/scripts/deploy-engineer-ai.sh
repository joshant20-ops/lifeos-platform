#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
BACKEND="$REPO/governor/engineer_backend.py"
BACKEND_PORT=8793
DEPLOY_PHASE=preflight
FAILURE_DIAGNOSTICS_ACTIVE=false

wait_for_health() {
  local name=$1 url=$2 deadline=${3:-60} delay=1 started now
  started=$(date +%s)
  while true; do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      printf '%s_HEALTH=PASS elapsed=%ss\n' "$name" "$(( $(date +%s) - started ))"
      return 0
    fi
    now=$(date +%s)
    if (( now - started >= deadline )); then
      printf '%s_HEALTH=FAIL url=%s timeout=%ss\n' "$name" "$url" "$deadline" >&2
      return 1
    fi
    sleep "$delay"
    if (( delay < 16 )); then delay=$((delay * 2)); fi
  done
}

backend_diagnostics() {
  printf '\n===== ENGINEER BACKEND FAILURE DIAGNOSTICS =====\n' >&2
  systemctl --no-pager --full status lifeos-engineer.service >&2 || true
  journalctl -u lifeos-engineer.service -n 200 --no-pager >&2 || true
  curl -v --max-time 5 "http://127.0.0.1:${BACKEND_PORT}/health" -o /dev/null >&2 || true
}

unexpected_failure() {
  local status=$? line=${1:-unknown}
  [[ "$FAILURE_DIAGNOSTICS_ACTIVE" == false ]] || exit "$status"
  FAILURE_DIAGNOSTICS_ACTIVE=true
  trap - ERR
  printf 'DEPLOYMENT_FAILURE=unexpected phase=%s line=%s exit=%s\n' "$DEPLOY_PHASE" "$line" "$status" >&2
  backend_diagnostics
  exit "$status"
}
trap 'unexpected_failure "$LINENO"' ERR

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS ENGINEER BACKEND VERIFY =====\n'
printf 'Presentation: Home Assistant / LifeOS surfaces\n'
printf 'Conversation backend: lifeos-engineer.service\n'
printf 'OpenWebUI: retired from desired runtime\n\n'

printf '===== 1/4 — SOURCE =====\n'
printf 'HEAD=%s\n' "$(git -C "$REPO" rev-parse --short HEAD)"

printf '\n===== 2/4 — PREFLIGHT =====\n'
python3 -m py_compile "$BACKEND"
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null
printf 'PREFLIGHT=PASS\n'

printf '\n===== 3/4 — ENGINEER BACKEND =====\n'
DEPLOY_PHASE=backend
LIVE_BACKEND=/usr/local/libexec/lifeos-engineer
ENGINEER_UNIT=/etc/systemd/system/lifeos-engineer.service
if [[ ! -f "$LIVE_BACKEND" || ! -f "$ENGINEER_UNIT" ]]; then
  printf 'PRIVILEGED_BOOTSTRAP_REQUIRED component=engineer_backend reason=missing_installation\n'
  exit 30
fi
if ! cmp -s "$BACKEND" "$LIVE_BACKEND"; then
  printf 'PRIVILEGED_BOOTSTRAP_REQUIRED component=engineer_backend reason=installed_binary_outdated\n'
  printf 'SOURCE_SHA256=%s\n' "$(sha256sum "$BACKEND" | awk '{print $1}')"
  printf 'LIVE_SHA256=%s\n' "$(sha256sum "$LIVE_BACKEND" | awk '{print $1}')"
  exit 30
fi
if ! systemctl is-active --quiet lifeos-engineer.service; then
  printf 'PRIVILEGED_BOOTSTRAP_REQUIRED component=engineer_backend reason=service_not_running\n'
  backend_diagnostics
  exit 30
fi
wait_for_health ENGINEER_BACKEND "http://127.0.0.1:${BACKEND_PORT}/health" 60
printf 'ENGINEER_BACKEND=PASS mode=unprivileged_runtime\n'

printf '\n===== 4/4 — OPENAI COMPATIBILITY =====\n'
DEPLOY_PHASE=verification
MODELS=$(curl -fsS --max-time 5 http://127.0.0.1:${BACKEND_PORT}/v1/models)
python3 - "$MODELS" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
ids=[m.get('id') for m in j.get('data',[])]
assert 'lifeos-engineer' in ids
print('MODEL_DISCOVERY=PASS')
PY
TEST=$(curl -fsS --max-time 120 -H 'Content-Type: application/json' \
  -d '{"model":"lifeos-engineer","stream":false,"messages":[{"role":"user","content":"I want to improve a LifeOS dashboard. Do not execute anything; understand the request and tell me what you would clarify or improve."}]}' \
  http://127.0.0.1:${BACKEND_PORT}/v1/chat/completions)
python3 - "$TEST" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
msg=j['choices'][0]['message']['content']
assert msg
assert 'run it' in msg.lower() or '?' in msg
print('ENGINEER_CONVERSATION=PASS')
PY

DEPLOY_PHASE=complete
printf 'RESULT=PASS\n'
printf 'ROLE=engineering_conversation_backend\n'
printf 'PRESENTATION=Home_Assistant_or_LifeOS_native_surfaces\n'
printf 'OPENWEBUI=RETIRED\n'
printf 'APPROVAL_REQUIRED=explicit_run_it_before_execution\n'
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
