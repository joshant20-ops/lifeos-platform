#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
BACKEND="$REPO/governor/engineer_backend.py"
OWUI_IMAGE="ghcr.io/open-webui/open-webui:v0.11.1"
OWUI_PORT=8792
BACKEND_PORT=8793

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS ENGINEER AI DEPLOY =====\n'
printf 'Frontend: Open WebUI v0.11.1\n'
printf 'Conversation/planning: local Qwen\n'
printf 'Execution: Pi5 autonomous agent -> Engineer Codex -> Pi5 -> TowerPC Qwen verifier\n\n'

printf '===== 1/8 — SYNC =====\n'
git -C "$REPO" fetch origin main
git -C "$REPO" reset --hard origin/main
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
for _ in $(seq 1 20); do
  curl -fsS --max-time 3 http://127.0.0.1:${BACKEND_PORT}/health >/dev/null && break
  sleep 1
done
curl -fsS --max-time 3 http://127.0.0.1:${BACKEND_PORT}/health >/dev/null
printf 'ENGINEER_BACKEND=PASS\n'

printf '\n===== 4/8 — OPEN WEBUI =====\n'
sudo install -d -m 0750 -o joshan -g joshan /var/lib/lifeos-openwebui
SECRET_FILE=/var/lib/lifeos-openwebui/webui-secret
if [[ ! -s "$SECRET_FILE" ]]; then
  umask 077
  openssl rand -hex 32 > "$SECRET_FILE"
fi
WEBUI_SECRET_KEY=$(cat "$SECRET_FILE")

docker pull "$OWUI_IMAGE" >/dev/null
if docker ps -a --format '{{.Names}}' | grep -qx lifeos-engineer-ui; then
  docker rm -f lifeos-engineer-ui >/dev/null
fi

docker run -d \
  --name lifeos-engineer-ui \
  --restart unless-stopped \
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

for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:${OWUI_PORT}/ >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS --max-time 5 http://127.0.0.1:${OWUI_PORT}/ >/dev/null
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
HA_JOB=$(cat <<EOF
Replace the prototype LifeOS Assistant engineering surface in Home Assistant with the dedicated LifeOS Engineer interface at ${ENGINEER_URL}. This is the engineering AI only; do not create or redesign the future personal-assistant/PA UI as part of this job.

Requirements:
- Make LifeOS Engineer a first-class, easy-to-reach technical/engineering surface in Home Assistant, ideally a dedicated LifeOS Engineer view or safe sidebar/panel entry; otherwise use a full-width iframe/Webpage card on the most appropriate existing LifeOS dashboard.
- If the earlier prototype LifeOS Assistant iframe/card/sidebar entry exists only for engineering, replace or rename it rather than leaving duplicate engineering interfaces.
- Do not remove unrelated LifeOS, energy, household or future-PA cards.
- Preserve existing dashboard style and layout.
- Open WebUI is running on the trusted LAN at ${ENGINEER_URL}; keep it LAN-only and do not expose it publicly.
- Home Assistant private runtime discovery must stay local. Do not send secrets, tokens, entity history or private HA data to cloud Codex.
- Back up any HA configuration changed; use supported HA configuration/API mechanisms and do not directly corrupt storage-mode dashboard files.
- Validate HA configuration before reload/restart and make the change reversible.
- Verify from the HA side where possible that the Open WebUI page loads.
- Report the final HA navigation path/view and whether the old prototype engineering surface was removed/replaced.
- Do not attempt PA functionality in this job. PA is a separate future role that LifeOS Engineer will help build later.
EOF
)
HA_JSON=$(python3 - "$HA_JOB" <<'PY'
import json,sys
print(json.dumps({'request':sys.argv[1]}))
PY
)
HA_SUBMIT=$(curl -fsS --max-time 15 -H 'Content-Type: application/json' -d "$HA_JSON" 'http://127.0.0.1:8790/jobs?async=1')
python3 - "$HA_SUBMIT" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['status']=='QUEUED'
print('HA_ENGINEER_JOB='+j['id'])
print('HA_ENGINEER_STATUS='+j['status'])
PY

printf '\n===== 8/8 — RESULT =====\n'
printf 'RESULT=PASS\n'
printf 'ROLE=engineering_only\n'
printf 'PA_ROLE=separate_future_surface\n'
printf 'APPROVAL_REQUIRED=explicit_run_it_before_execution\n'
printf 'ENGINEERING_LOOP=Pi5_to_Engineer_Codex_to_Pi5_to_TowerPC_Qwen\n'
printf 'OPENWEBUI_VERSION=v0.11.1\n'
printf 'FIRST_USE=Create_the_first_Open_WebUI_admin_account_then_select_lifeos-engineer\n'
printf 'NOTE=Home_Assistant_Engineer_integration_continues_as_autonomous_job\n'
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
