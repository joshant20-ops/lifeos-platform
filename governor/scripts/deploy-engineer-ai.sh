#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
BACKEND="$REPO/governor/engineer_backend.py"
OWUI_IMAGE="ghcr.io/open-webui/open-webui:v0.11.1"
OWUI_PORT=8792
BACKEND_PORT=8793
UI_NAME=lifeos-engineer-ui
UI_HEALTH_URL="http://127.0.0.1:${OWUI_PORT}/health"

wait_for_health() {
  local name=$1 url=$2 deadline=${3:-300} delay=1 started now
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
    printf '%s_HEALTH=WAIT elapsed=%ss next_retry=%ss\n' "$name" "$((now - started))" "$delay"
    sleep "$delay"
    # Do not use a short-circuit arithmetic expression here: once delay is 16,
    # its false status would terminate this script because set -e is enabled.
    if (( delay < 16 )); then
      delay=$((delay * 2))
    fi
  done
}

ui_diagnostics() {
  printf '\n===== OPEN WEBUI FAILURE DIAGNOSTICS =====\n' >&2
  docker ps -a --filter "name=^/${UI_NAME}$" --no-trunc >&2 || true
  docker inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} exit={{.State.ExitCode}} error={{.State.Error}} started={{.State.StartedAt}}' "$UI_NAME" >&2 || true
  docker logs --tail 200 --timestamps "$UI_NAME" >&2 || true
  curl -v --max-time 5 "$UI_HEALTH_URL" -o /dev/null >&2 || true
}

backend_diagnostics() {
  printf '\n===== ENGINEER BACKEND FAILURE DIAGNOSTICS =====\n' >&2
  systemctl --no-pager --full status lifeos-engineer.service >&2 || true
  journalctl -u lifeos-engineer.service -n 200 --no-pager >&2 || true
  curl -v --max-time 5 "http://127.0.0.1:${BACKEND_PORT}/health" -o /dev/null >&2 || true
}

ui_container_health() {
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "$UI_NAME" 2>/dev/null || printf 'missing\n'
}

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS ENGINEER AI DEPLOY =====\n'
printf 'Frontend: Open WebUI v0.11.1\n'
printf 'Conversation/planning: local Qwen\n'
printf 'Execution: Pi5 autonomous agent -> Engineer Codex -> Pi5 -> TowerPC Qwen verifier\n\n'

printf '===== 1/8 — SOURCE =====\n'
printf 'HEAD=%s\n' "$(git -C "$REPO" rev-parse --short HEAD)"

printf '\n===== 2/8 — PREFLIGHT =====\n'
python3 -m py_compile "$BACKEND"
command -v docker >/dev/null
docker info >/dev/null
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null
curl -fsS --max-time 5 http://192.168.0.201:11434/api/tags >/dev/null
printf 'PREFLIGHT=PASS\n'

printf '\n===== 3/8 — ENGINEER BACKEND =====\n'
sudo install -m 0755 "$BACKEND" /usr/local/libexec/lifeos-engineer
sudo tee /etc/systemd/system/lifeos-engineer.service >/dev/null <<'UNIT'
[Unit]
Description=LifeOS Engineer OpenAI-compatible conversational backend
After=network-online.target lifeos-autonomous-agent.service
Wants=network-online.target
Requires=lifeos-autonomous-agent.service

[Service]
Type=simple
User=joshan
Group=joshan
Environment=LIFEOS_ENGINEER_PORT=8793
Environment=LIFEOS_AGENT_URL=http://127.0.0.1:8790
Environment=LIFEOS_ENGINEER_MODEL_URL=http://192.168.0.201:11434/api/generate
Environment=LIFEOS_ENGINEER_MODEL=qwen2.5-coder:7b-instruct
ExecStart=/usr/local/libexec/lifeos-engineer
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl restart lifeos-engineer.service
sudo systemctl enable lifeos-engineer.service >/dev/null
if ! wait_for_health ENGINEER_BACKEND "http://127.0.0.1:${BACKEND_PORT}/health" 60; then
  backend_diagnostics
  exit 1
fi
printf 'ENGINEER_BACKEND=PASS\n'

printf '\n===== 4/8 — OPEN WEBUI =====\n'
sudo install -d -m 0750 -o joshan -g joshan /var/lib/lifeos-openwebui
SECRET_FILE=/var/lib/lifeos-openwebui/webui-secret
if [[ ! -s "$SECRET_FILE" ]]; then
  umask 077
  openssl rand -hex 32 > "$SECRET_FILE"
fi
WEBUI_SECRET_KEY=$(cat "$SECRET_FILE")

RECREATE_UI=true
if docker ps --format '{{.Names}}' | grep -qx "$UI_NAME"; then
  UI_DOCKER_HEALTH=$(ui_container_health)
  printf 'OPEN_WEBUI_EXISTING=running docker_health=%s\n' "$UI_DOCKER_HEALTH"
  # Docker's healthcheck also calls /health. Preserve a container that has
  # already passed that readiness contract even if this one host-side probe is
  # affected by a transient bridge/published-port problem.
  if [[ "$UI_DOCKER_HEALTH" == healthy ]]; then
    printf 'OPEN_WEBUI_REUSED=healthy_existing_container source=docker_health\n'
    RECREATE_UI=false
  # Open WebUI can take several minutes to migrate its database on the first
  # start (or after an image upgrade).  Give the existing process the same
  # readiness budget as a new one before deciding that it has failed.
  elif wait_for_health OPEN_WEBUI_EXISTING "$UI_HEALTH_URL" 300; then
    printf 'OPEN_WEBUI_REUSED=healthy_existing_container source=host_health\n'
    RECREATE_UI=false
  elif [[ "$(ui_container_health)" == healthy ]]; then
    # Close the race where Docker records a successful /health probe just as
    # the host-side readiness budget expires.
    printf 'OPEN_WEBUI_REUSED=healthy_existing_container source=docker_health_after_wait\n'
    RECREATE_UI=false
  else
    printf 'OPEN_WEBUI_EXISTING=failed_readiness_will_recreate\n' >&2
    ui_diagnostics
  fi
fi

if [[ "$RECREATE_UI" == true ]]; then
  docker pull "$OWUI_IMAGE" >/dev/null
  if docker ps -a --format '{{.Names}}' | grep -qx "$UI_NAME"; then
    printf 'OPEN_WEBUI_RECREATE=existing_container_failed_or_stopped\n'
    # A stopped container has not been diagnosed above.
    if ! docker ps --format '{{.Names}}' | grep -qx "$UI_NAME"; then
      ui_diagnostics
    fi
    docker rm -f "$UI_NAME" >/dev/null
  fi

  docker run -d \
  --name "$UI_NAME" \
  --restart unless-stopped \
  --health-cmd='python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8080/health\", timeout=5).read()"' \
  --health-interval=15s \
  --health-timeout=10s \
  --health-start-period=300s \
  --health-retries=3 \
  -p ${OWUI_PORT}:8080 \
  --add-host=host.docker.internal:host-gateway \
  -v lifeos-engineer-openwebui:/app/backend/data \
  -e WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY" \
  -e ENABLE_OLLAMA_API=false \
  -e ENABLE_OPENAI_API=true \
  -e OPENAI_API_BASE_URL="http://host.docker.internal:${BACKEND_PORT}/v1" \
  -e OPENAI_API_KEY="lifeos-local" \
  -e WEBUI_NAME="LifeOS Engineer" \
  "$OWUI_IMAGE" >/dev/null
fi

if ! wait_for_health OPEN_WEBUI "$UI_HEALTH_URL" 300; then
  ui_diagnostics
  exit 1
fi
printf 'OPEN_WEBUI=PASS\n'

printf '\n===== 5/8 — OPENAI COMPATIBILITY TEST =====\n'
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

printf '\n===== 6/8 — NETWORK + HA TARGET =====\n'
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[[ -n "${LAN_IP:-}" ]] || LAN_IP=Docker
ENGINEER_URL="http://${LAN_IP}:${OWUI_PORT}/"
printf 'ENGINEER_URL=%s\n' "$ENGINEER_URL"
printf 'BACKEND_URL=http://%s:%s/v1\n' "$LAN_IP" "$BACKEND_PORT"
printf 'HA_CARD_FALLBACK_BEGIN\n'
cat <<YAML
type: iframe
url: ${ENGINEER_URL}
aspect_ratio: 100%%
title: LifeOS Engineer
YAML
printf 'HA_CARD_FALLBACK_END\n'

printf '\n===== 7/8 — HOME ASSISTANT ENGINEER INTEGRATION =====\n'
printf 'HA_INTEGRATION=managed_by_runtime_job\n'
printf 'HA_INTEGRATION_TARGET=sidebar_LifeOS_Engineer\n'

printf '\n===== 8/8 — RESULT =====\n'
printf 'RESULT=PASS\n'
printf 'ROLE=engineering_only\n'
printf 'PA_ROLE=separate_future_surface\n'
printf 'APPROVAL_REQUIRED=explicit_run_it_before_execution\n'
printf 'ENGINEERING_LOOP=Pi5_to_Engineer_Codex_to_Pi5_to_TowerPC_Qwen\n'
printf 'OPENWEBUI_VERSION=v0.11.1\n'
printf 'FIRST_USE=Create_the_first_Open_WebUI_admin_account_then_select_lifeos-engineer\n'
printf 'NOTE=Home_Assistant_integration_is_applied_and_verified_by_the_Pi5_runtime_job\n'
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
