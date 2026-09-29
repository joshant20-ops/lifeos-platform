#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
BRIDGE="$REPO/governor/assistant_bridge.py"
UI="$REPO/governor/assistant_ui.html"
PORT=8791

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS HOME ASSISTANT AI DEPLOY =====\n'

printf '\n===== 1/6 — CANONICAL CHECKOUT =====\n'
# The root-owned deployment gateway already requires this checkout to be clean
# and exactly aligned with origin/main before invoking this script. Do not
# perform network Git operations here: the child executes as root and must not
# inherit or require the unprivileged runner/user GitHub credentials.
printf 'HEAD=%s\n' "$(git -C "$REPO" rev-parse --short HEAD)"
test -z "$(git -C "$REPO" status --porcelain)"

printf '\n===== 2/6 — PREFLIGHT =====\n'
python3 -m py_compile "$BRIDGE"
test -s "$UI"
grep -q 'LifeOS Assistant' "$UI"
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null
# Do not require the Tower/Ollama endpoint to be awake here. The assistant
# imports ai_broker, whose local inference path owns the MQTT lease, WoL and
# readiness retry lifecycle. The conversational acceptance below exercises it.
python3 -m py_compile "$REPO/governor/ai_broker.py"
printf 'PREFLIGHT=PASS\n'

printf '\n===== 3/6 — INSTALL =====\n'
sudo install -d -o root -g root -m 0755 /usr/local/libexec/lifeos-assistant.d
sudo install -m 0755 "$BRIDGE" /usr/local/libexec/lifeos-assistant.d/assistant_bridge.py
sudo install -m 0644 "$REPO/governor/ai_broker.py" /usr/local/libexec/lifeos-assistant.d/ai_broker.py
sudo install -m 0644 "$REPO/governor/privacy-domain-policy.json" /usr/local/libexec/lifeos-assistant.d/privacy-domain-policy.json
sudo install -m 0644 "$REPO/governor/policy.json" /usr/local/libexec/lifeos-assistant.d/policy.json
sudo install -m 0644 "$REPO/engineer/provider_router.py" /usr/local/libexec/lifeos-assistant.d/provider_router.py
sudo install -m 0644 "$UI" /usr/local/share/lifeos-assistant.html
sudo python3 -m py_compile /usr/local/libexec/lifeos-assistant.d/assistant_bridge.py /usr/local/libexec/lifeos-assistant.d/ai_broker.py  /usr/local/libexec/lifeos-assistant.d/provider_router.py

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
Environment=LIFEOS_ASSISTANT_UI=/usr/local/share/lifeos-assistant.html
WorkingDirectory=/usr/local/libexec/lifeos-assistant.d
Environment=PYTHONPATH=/usr/local/libexec/lifeos-assistant.d
Environment=LIFEOS_AI_POLICY=/usr/local/libexec/lifeos-assistant.d/policy.json
Environment=LIFEOS_PROVIDER_ROUTER=/usr/local/libexec/lifeos-assistant.d/provider_router.py
RuntimeDirectory=lifeos-assistant
RuntimeDirectoryMode=0700
Environment=LIFEOS_AI_BROKER_CONFIG=/run/lifeos-assistant/ai-broker.env
Environment=LIFEOS_PROVIDER_SECRETS=/run/lifeos-assistant/provider-secrets.env
ExecStartPre=+/usr/bin/install -o joshan -g joshan -m 0600 /home/joshan/.config/lifeos/ai-broker.env /run/lifeos-assistant/ai-broker.env
ExecStartPre=+/usr/bin/install -o joshan -g joshan -m 0600 /home/joshan/.config/lifeos/provider-secrets.env /run/lifeos-assistant/provider-secrets.env
ExecStart=/usr/bin/python3 /usr/local/libexec/lifeos-assistant.d/assistant_bridge.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT

# Validate required private runtime inputs before restarting. ExecStartPre copies
# them into the service's private /run directory as strict 0600 regular files,
# satisfying provider_router's fail-closed secret-file contract without exposing
# the user's home to the running service.
sudo test -r /home/joshan/.config/lifeos/ai-broker.env
sudo test -r /home/joshan/.config/lifeos/provider-secrets.env

sudo systemctl daemon-reload
sudo systemctl restart lifeos-assistant.service
sudo systemctl enable lifeos-assistant.service >/dev/null

printf '\n===== 4/6 — VERIFY =====\n'
for _ in $(seq 1 20); do
  if curl -fsS --max-time 3 http://127.0.0.1:${PORT}/health >/dev/null; then break; fi
  sleep 1
done
if ! curl -fsS --max-time 3 http://127.0.0.1:${PORT}/health >/dev/null; then
  sudo systemctl status lifeos-assistant.service --no-pager -l || true
  sudo journalctl -u lifeos-assistant.service -n 40 --no-pager || true
  exit 7
fi
HEALTH=$(curl -fsS --max-time 3 http://127.0.0.1:${PORT}/health)
python3 - "$HEALTH" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['status']=='ok'
assert j['agent']=='ok'
assert j['inference']=='governor-routed'
print('ASSISTANT_HEALTH=PASS')
print('INFERENCE='+j['inference'])
PY
curl -fsS --max-time 3 http://127.0.0.1:${PORT}/ | grep -q 'LifeOS Assistant'
TEST=$(curl -sS --max-time 360 -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"I want a read-only health check for LifeOS. Understand the goal and suggest one useful improvement, but do not run anything."}],"privacy_domain":"personal-administration"}' \
  -w '\n%{http_code}' http://127.0.0.1:${PORT}/assist)
TEST_CODE="${TEST##*
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

printf '\n===== 6/6 — DEPLOYMENT RESULT =====\n'
printf 'RESULT=PASS\n'
printf 'PRIVACY=pa_conversation_local_only\n'
printf 'NOTE=Home_Assistant_target_reported_without_enqueuing_duplicate_engineering_jobs\n'
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
