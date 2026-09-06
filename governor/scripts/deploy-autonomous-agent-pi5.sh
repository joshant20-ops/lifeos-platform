#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
AGENT_CORE="$REPO/governor/autonomous_agent.py"
AGENT_SERVER="$REPO/governor/autonomous_agent_server.py"
AI_BROKER="$REPO/governor/ai_broker.py"
PRIVACY_POLICY="$REPO/governor/privacy-domain-policy.json"
BUILDER_SRC="$REPO/governor/scripts/lifeos-cloud-builder"
UI="$REPO/governor/agent_ui.html"
BROKER_TOKEN="$HOME/.config/lifeos/ai-broker.token"

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS AUTONOMOUS AGENT DEPLOY =====\n'
printf 'Controller/Git/runtime: Pi5/Docker\n'
printf 'Inference authority: Pi5 Governor broker\n'
printf 'Agentic executor: OpenHands/Codex on Engineer when required\n'
printf 'Verifier: local Qwen on TowerPC\n\n'

printf '===== 1/8 — SYNC =====\n'
git -C "$REPO" fetch origin main
git -C "$REPO" reset --hard origin/main
printf 'HEAD=%s\n' "$(git -C "$REPO" rev-parse --short HEAD)"

printf '\n===== 2/8 — PREFLIGHT =====\n'
python3 -m py_compile "$AGENT_CORE" "$AGENT_SERVER" "$AI_BROKER"
python3 -m json.tool "$PRIVACY_POLICY" >/dev/null
bash -n "$BUILDER_SRC"
test -s "$UI"
grep -q 'LifeOS Autonomous Agent' "$UI"
ssh -o BatchMode=yes -o ConnectTimeout=5 Engineer '
OPENHANDS="$HOME/.local/bin/openhands"
test -x "$OPENHANDS"
echo "$OPENHANDS"
"$OPENHANDS" --version
' | head -3
printf 'PREFLIGHT=PASS\n'

printf '\n===== 3/8 — BROKER CAPABILITY =====\n'
install -d -m 0700 "$HOME/.config/lifeos"
if [[ ! -s "$BROKER_TOKEN" ]]; then
  umask 077
  python3 - <<'PY' >"$BROKER_TOKEN"
import secrets
print(secrets.token_urlsafe(48))
PY
fi
chmod 0600 "$BROKER_TOKEN"
test -f "$BROKER_TOKEN"
test ! -L "$BROKER_TOKEN"
test "$(stat -c '%a' "$BROKER_TOKEN")" = 600
test -s "$HOME/.config/lifeos/provider-secrets.env"
test "$(stat -c '%a' "$HOME/.config/lifeos/provider-secrets.env")" = 600
printf 'BROKER_CAPABILITY=PASS\n'

printf '\n===== 4/8 — INSTALL =====\n'
sudo install -m 0755 "$AGENT_CORE" /usr/local/libexec/lifeos-autonomous-agent-core
sudo install -m 0755 "$AGENT_SERVER" /usr/local/libexec/lifeos-autonomous-agent
sudo install -m 0644 "$PRIVACY_POLICY" /usr/local/libexec/privacy-domain-policy.json
sudo install -m 0755 "$BUILDER_SRC" /usr/local/libexec/lifeos-cloud-builder
sudo install -d -m 0750 -o joshan -g joshan /var/lib/lifeos-agent

sudo tee /etc/systemd/system/lifeos-autonomous-agent.service >/dev/null <<'UNIT'
[Unit]
Description=LifeOS autonomous natural-language job agent and AI policy broker
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=joshan
Group=joshan
Environment=LIFEOS_AGENT_PORT=8790
Environment=LIFEOS_AGENT_STATE=/var/lib/lifeos-agent
Environment=LIFEOS_AGENT_MAX_ITERATIONS=8
Environment=LIFEOS_AGENT_BUILDER=/usr/local/libexec/lifeos-cloud-builder
Environment=LIFEOS_AGENT_CORE=/usr/local/libexec/lifeos-autonomous-agent-core
Environment=LIFEOS_PRIVACY_DOMAIN_POLICY=/usr/local/libexec/privacy-domain-policy.json
Environment=LIFEOS_LOCAL_VERIFIER_URL=http://192.168.0.201:11434/api/generate
Environment=LIFEOS_LOCAL_VERIFIER_MODEL=qwen2.5-coder:7b-instruct
Environment=LIFEOS_PLATFORM_REPO=/home/joshan/lifeos-platform
Environment=LIFEOS_AI_BROKER_TOKEN_FILE=/home/joshan/.config/lifeos/ai-broker.token
Environment=LIFEOS_PROVIDER_SECRETS=/home/joshan/.config/lifeos/provider-secrets.env
ExecStart=/usr/local/libexec/lifeos-autonomous-agent
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/lifeos-agent /home/joshan/lifeos-platform

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl restart lifeos-autonomous-agent.service
sudo systemctl enable lifeos-autonomous-agent.service >/dev/null

printf '\n===== 5/8 — HEALTH + BROKER =====\n'
for _ in $(seq 1 20); do
  if curl -fsS --max-time 3 http://127.0.0.1:8790/health >/dev/null; then break; fi
  sleep 1
done
HEALTH=$(curl -fsS --max-time 3 http://127.0.0.1:8790/health)
python3 - "$HEALTH" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['status']=='ok'
assert j['runtime_controller']=='pi5'
assert j['git_controller']=='pi5'
print('AGENT_HEALTH=PASS')
PY
code=$(curl -sS -o /tmp/lifeos-broker-unauth.json -w '%{http_code}' --max-time 10 \
  -H 'Content-Type: application/json' \
  -d '{"model":"lifeos-normal","messages":[{"role":"user","content":"test"}]}' \
  http://127.0.0.1:8790/v1/chat/completions)
test "$code" = 401
rm -f /tmp/lifeos-broker-unauth.json
printf 'BROKER_UNAUTHENTICATED_REJECT=PASS\n'
BROKER_REQ=$(python3 - <<'PY'
import json
print(json.dumps({"model":"lifeos-normal","messages":[{"role":"user","content":"Reply with exactly LIFEOS_GOVERNOR_BROKER_OK"}]}))
PY
)
BROKER_OUT=$(curl -fsS --max-time 120 \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $(cat "$BROKER_TOKEN")" \
  -d "$BROKER_REQ" http://127.0.0.1:8790/v1/chat/completions)
python3 - "$BROKER_OUT" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
text=str(j['choices'][0]['message']['content'])
assert 'LIFEOS_GOVERNOR_BROKER_OK' in text, text[:200]
assert j['lifeos_privacy']=='normal'
assert j['lifeos_provider'] in {'gemini','openrouter','cloudflare'}
print('BROKER_AUTHENTICATED_INFERENCE=PASS')
print('BROKER_PROVIDER='+j['lifeos_provider'])
PY

printf '\n===== 6/8 — UI + PRIVACY FAIL-CLOSED =====\n'
curl -fsS --max-time 3 http://127.0.0.1:8790/ | grep -q 'LifeOS Autonomous Agent'
JOBS=$(curl -fsS --max-time 3 http://127.0.0.1:8790/jobs)
python3 - "$JOBS" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert isinstance(j.get('jobs'), list)
print('AGENT_UI=PASS')
print('JOB_LIST_API=PASS')
PY
PRIVATE_OUT=$(curl -fsS --max-time 60 -H 'Content-Type: application/json' \
  -d '{"request":"Summarize upcoming appointments","privacy_domain":"personal-administration"}' \
  http://127.0.0.1:8790/jobs)
python3 - "$PRIVATE_OUT" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['privacy']=='local-only'
assert j['privacy_domain']=='personal-administration'
assert j['status']=='BLOCKED'
assert not any('PI5_PATCH=APPLIED' in x.get('evidence','') for x in j.get('iterations',[]))
print('PRIVACY_BOUNDARY=PASS')
PY

printf '\n===== 7/8 — TRUE END-TO-END AUTONOMOUS SMOKE =====\n'
SMOKE_REQ='Prove the LifeOS autonomous runtime loop works. In your disposable Engineer worktree, create the required per-job Pi5 runtime launcher but do not commit or push it yourself; Pi5 owns Git publication. The launcher must safely and read-only curl http://127.0.0.1:8790/health from Pi5, verify service=lifeos-autonomous-agent, status=ok, runtime_controller=pi5, git_controller=pi5, print RUNTIME_LOOP_SMOKE=PASS, and make no other system changes. Run focused tests and leave the launcher in the worktree for automatic handoff. Unrelated repository failures are not blockers.'
SMOKE_JSON=$(python3 - "$SMOKE_REQ" <<'PY'
import json,sys
print(json.dumps({'request':sys.argv[1]}))
PY
)
SMOKE=$(curl -fsS --max-time 1100 -H 'Content-Type: application/json' \
  -d "$SMOKE_JSON" http://127.0.0.1:8790/jobs)
python3 - "$SMOKE" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
print('JOB_ID='+j['id'])
print('STATUS='+j['status'])
print('ITERATIONS='+str(len(j.get('iterations',[]))))
published=False
runtime=False
for x in j.get('iterations',[]):
    ev=str(x.get('evidence',''))
    if 'PI5_PATCH=APPLIED' in ev and 'PI5_PUSH=PASS' in ev:
        published=True
        print('PI5_GIT_PUBLICATION=PASS')
    if 'RUNTIME_LOOP_SMOKE=PASS' in ev and 'RUNTIME_RC=0' in ev:
        runtime=True
        print('PI5_RUNTIME_EVIDENCE=PASS')
if j['status'] != 'PASS':
    print('BLOCKED_REASON='+str(j.get('blocked_reason')))
    raise SystemExit('AUTONOMOUS_E2E_SMOKE_DID_NOT_PASS')
assert published, 'missing Pi5-owned Git publication evidence'
assert runtime, 'missing Pi5 runtime evidence'
print('AUTONOMOUS_LOOP=PASS')
PY

printf '\n===== 8/8 — RESULT =====\n'
printf 'RESULT=PASS\n'
printf 'CONTROLLER=Pi5\n'
printf 'INFERENCE_AUTHORITY=Pi5_Governor\n'
printf 'CLOUD_INFERENCE_REQUIRES_ENGINEER=NO\n'
printf 'AGENTIC_EXECUTOR=Engineer_OpenHands_or_Codex\n'
printf 'PRIVATE_DOMAINS_TO_CLOUD=blocked\n'
printf 'BROKER_API=http://127.0.0.1:8790/v1\n'
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [[ -n "${LAN_IP:-}" ]]; then
  printf 'LAN_BROKER_API=http://%s:8790/v1\n' "$LAN_IP"
  printf 'UI=http://%s:8790/\n' "$LAN_IP"
else
  printf 'LAN_BROKER_API=http://Docker:8790/v1\n'
  printf 'UI=http://Docker:8790/\n'
fi
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
