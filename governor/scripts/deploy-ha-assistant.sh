#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
BRIDGE="$REPO/governor/assistant_bridge.py"
UI="$REPO/governor/assistant_ui.html"
PORT=8791

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS HOME ASSISTANT AI DEPLOY =====\n'

printf '\n===== 1/6 — SYNC =====\n'
git -C "$REPO" fetch origin main
git -C "$REPO" reset --hard origin/main
printf 'HEAD=%s\n' "$(git -C "$REPO" rev-parse --short HEAD)"

printf '\n===== 2/6 — PREFLIGHT =====\n'
python3 -m py_compile "$BRIDGE"
test -s "$UI"
grep -q 'LifeOS Assistant' "$UI"
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null
curl -fsS --max-time 5 http://192.168.0.201:11434/api/tags >/dev/null
printf 'PREFLIGHT=PASS\n'

printf '\n===== 3/6 — INSTALL =====\n'
sudo install -m 0755 "$BRIDGE" /usr/local/libexec/lifeos-assistant
sudo install -m 0644 "$UI" /usr/local/share/lifeos-assistant.html

sudo tee /etc/systemd/system/lifeos-assistant.service >/dev/null <<'UNIT'
[Unit]
Description=LifeOS conversational assistant for Home Assistant
After=network-online.target lifeos-autonomous-agent.service
Wants=network-online.target
Requires=lifeos-autonomous-agent.service

[Service]
Type=simple
User=joshan
Group=joshan
Environment=LIFEOS_ASSISTANT_PORT=8791
Environment=LIFEOS_AGENT_URL=http://127.0.0.1:8790
Environment=LIFEOS_ASSISTANT_MODEL_URL=http://192.168.0.201:11434/api/generate
Environment=LIFEOS_ASSISTANT_MODEL=qwen2.5-coder:7b-instruct
Environment=LIFEOS_ASSISTANT_UI=/usr/local/share/lifeos-assistant.html
ExecStart=/usr/local/libexec/lifeos-assistant
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
sudo systemctl restart lifeos-assistant.service
sudo systemctl enable lifeos-assistant.service >/dev/null

printf '\n===== 4/6 — VERIFY =====\n'
for _ in $(seq 1 20); do
  if curl -fsS --max-time 3 http://127.0.0.1:${PORT}/health >/dev/null; then break; fi
  sleep 1
done
HEALTH=$(curl -fsS --max-time 3 http://127.0.0.1:${PORT}/health)
python3 - "$HEALTH" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['status']=='ok'
assert j['agent']=='ok'
print('ASSISTANT_HEALTH=PASS')
print('LOCAL_MODEL='+j['model'])
PY
curl -fsS --max-time 3 http://127.0.0.1:${PORT}/ | grep -q 'LifeOS Assistant'
TEST=$(curl -fsS --max-time 90 -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"I want a read-only health check for LifeOS. Understand the goal and suggest one useful improvement, but do not run anything."}]}' \
  http://127.0.0.1:${PORT}/assist)
python3 - "$TEST" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert isinstance(j.get('reply'),str) and j['reply']
assert 'ready_to_run' in j
assert isinstance(j.get('improvements'),list)
print('CONVERSATION=PASS')
PY

printf '\n===== 5/6 — HOME ASSISTANT TARGET =====\n'
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[[ -n "${LAN_IP:-}" ]] || LAN_IP=Docker
ASSISTANT_URL="http://${LAN_IP}:${PORT}/"
printf 'ASSISTANT_URL=%s\n' "$ASSISTANT_URL"
printf 'HA_CARD_FALLBACK_BEGIN\n'
cat <<YAML
type: iframe
url: ${ASSISTANT_URL}
aspect_ratio: 100%%
title: LifeOS Assistant
YAML
printf 'HA_CARD_FALLBACK_END\n'

printf '\n===== 6/6 — CODEX HOME ASSISTANT INTEGRATION =====\n'
HA_JOB=$(cat <<EOF
Integrate the already-running LifeOS Assistant into the existing Home Assistant frontend as a first-class AI assistant surface. The assistant is reachable on the trusted LAN at ${ASSISTANT_URL} and must remain LAN-only.

Desired user experience:
- Put the LifeOS Assistant somewhere natural and easy to reach in Home Assistant, preferably as its own LifeOS/AI view or sidebar entry if that can be done safely with the current HA setup; otherwise use a full-width Webpage/iframe card on the existing LifeOS dashboard.
- Preserve the existing Home Assistant dashboard style and do not replace or remove existing cards.
- The primary surface must be the conversational assistant, not the raw autonomous job/debug UI.
- Verify the embedded page actually loads from Home Assistant's point of view where possible, not merely that YAML parses.
- Avoid duplicate cards or duplicate sidebar entries.
- Keep the assistant unavailable from the public internet.
- Do not expose HA secrets, tokens, credentials, entity history or private user data to cloud Codex. Runtime discovery requiring private HA data must happen locally on Pi5. Cloud Codex may author generic code/config only.
- If Home Assistant uses UI/storage-mode dashboards, do not directly corrupt .storage files. Prefer supported HA mechanisms/APIs or a safe configuration approach. Back up any configuration changed before applying it.
- Validate Home Assistant configuration before restart/reload, and make changes reversible.
- If the existing setup makes a direct sidebar panel unsafe, install the iframe card in the most appropriate existing LifeOS dashboard and report why.
- After installation, verify the assistant conversation UI is visible and that it can submit an approved engineering job to the existing Pi5 agent.

Return clear runtime evidence showing where it was added, validation results, and the final HA navigation path/view name.
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
print('HA_INTEGRATION_JOB='+j['id'])
print('HA_INTEGRATION_STATUS='+j['status'])
PY

printf 'RESULT=PASS\n'
printf 'PRIVACY=conversation_local_before_cloud_engineering\n'
printf 'NOTE=Home_Assistant_integration_continues_as_autonomous_job\n'
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
