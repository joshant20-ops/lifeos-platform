#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
AGENT="$REPO/governor/autonomous_agent.py"
BUILDER_SRC="$REPO/governor/scripts/lifeos-cloud-builder"

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS AUTONOMOUS AGENT DEPLOY =====\n'
printf 'Controller: Pi5/Docker\n'
printf 'Builder: cloud Codex on Engineer\n'
printf 'Verifier: local Qwen on TowerPC\n\n'

printf '===== 1/7 — SYNC =====\n'
git -C "$REPO" fetch origin main
git -C "$REPO" reset --hard origin/main
printf 'HEAD=%s\n' "$(git -C "$REPO" rev-parse --short HEAD)"

printf '\n===== 2/7 — PREFLIGHT =====\n'
python3 -m py_compile "$AGENT"
ssh -o BatchMode=yes -o ConnectTimeout=5 Engineer '
CODEX="$HOME/.local/bin/codex"
test -x "$CODEX"
echo "$CODEX"
"$CODEX" --version
' | head -3
curl -fsS --max-time 5 http://192.168.0.201:11434/api/tags >/dev/null
printf 'PREFLIGHT=PASS\n'

printf '\n===== 3/7 — INSTALL =====\n'
sudo install -m 0755 "$AGENT" /usr/local/libexec/lifeos-autonomous-agent
sudo install -m 0755 "$BUILDER_SRC" /usr/local/libexec/lifeos-cloud-builder
sudo install -d -m 0750 -o joshan -g joshan /var/lib/lifeos-agent

sudo tee /etc/systemd/system/lifeos-autonomous-agent.service >/dev/null <<'UNIT'
[Unit]
Description=LifeOS autonomous natural-language job agent
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
Environment=LIFEOS_LOCAL_VERIFIER_URL=http://192.168.0.201:11434/api/generate
Environment=LIFEOS_LOCAL_VERIFIER_MODEL=qwen2.5-coder:7b-instruct
ExecStart=/usr/local/libexec/lifeos-autonomous-agent
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/lifeos-agent
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now lifeos-autonomous-agent.service

printf '\n===== 4/7 — HEALTH =====\n'
for _ in $(seq 1 15); do
  if curl -fsS --max-time 3 http://127.0.0.1:8790/health; then echo; break; fi
  sleep 1
done
curl -fsS --max-time 3 http://127.0.0.1:8790/health >/dev/null
printf 'AGENT_HEALTH=PASS\n'

printf '\n===== 5/7 — PRIVACY FAIL-CLOSED TEST =====\n'
# This intentionally asks for a private-document job. The agent must refuse to use Codex.
PRIVATE_OUT=$(curl -fsS --max-time 30 -H 'Content-Type: application/json' \
  -d '{"request":"Read my private Paperless documents and summarize them"}' \
  http://127.0.0.1:8790/jobs)
python3 - "$PRIVATE_OUT" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
print('PRIVACY='+j['privacy'])
print('STATUS='+j['status'])
assert j['privacy']=='local-only'
assert j['status']=='BLOCKED'
assert 'cloud_builder_forbidden' in (j.get('blocked_reason') or '') or any('cloud_builder_forbidden' in x.get('evidence','') for x in j.get('iterations',[]))
print('PRIVACY_BOUNDARY=PASS')
PY

printf '\n===== 6/7 — NATURAL LANGUAGE SMOKE TEST =====\n'
# Use a harmless request that can be verified locally and does not require a system change.
SMOKE=$(curl -fsS --max-time 600 -H 'Content-Type: application/json' \
  -d '{"request":"Inspect the LifeOS governor implementation and verify it has a healthy local API. Do not make system changes unless needed to complete that verification."}' \
  http://127.0.0.1:8790/jobs)
python3 - "$SMOKE" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
print('JOB_ID='+j['id'])
print('STATUS='+j['status'])
print('ITERATIONS='+str(len(j.get('iterations',[]))))
if j['status'] not in ('PASS','BLOCKED'):
    raise SystemExit('unexpected terminal state')
PY

printf '\n===== 7/7 — RESULT =====\n'
printf 'RESULT=PASS\n'
printf 'INPUT=natural_language\n'
printf 'CONTROLLER=Pi5\n'
printf 'BUILDER=Engineer_Codex_cloud\n'
printf 'VERIFIER=TowerPC_Qwen_local\n'
printf 'ITERATES_TO=PASS_or_BLOCKED_or_8_iterations\n'
printf 'PRIVATE_DOCUMENTS_TO_CLOUD=blocked\n'
printf 'API=http://127.0.0.1:8790/jobs\n'
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
