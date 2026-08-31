#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
AGENT="$REPO/governor/autonomous_agent.py"
BUILDER_SRC="$REPO/governor/scripts/lifeos-cloud-builder"
UI="$REPO/governor/agent_ui.html"

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=must_run_on_pi5_Docker"; exit 20; }

printf '===== LIFEOS AUTONOMOUS AGENT DEPLOY =====\n'
printf 'Controller/Git/runtime: Pi5/Docker\n'
printf 'Builder: cloud Codex on Engineer\n'
printf 'Verifier: local Qwen on TowerPC\n\n'

printf '===== 1/7 — SYNC =====\n'
git -C "$REPO" fetch origin main
git -C "$REPO" reset --hard origin/main
printf 'HEAD=%s\n' "$(git -C "$REPO" rev-parse --short HEAD)"

printf '\n===== 2/7 — PREFLIGHT =====\n'
python3 -m py_compile "$AGENT"
bash -n "$BUILDER_SRC"
test -s "$UI"
grep -q 'LifeOS Autonomous Agent' "$UI"
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
Environment=LIFEOS_PLATFORM_REPO=/home/joshan/lifeos-platform
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

printf '\n===== 4/7 — HEALTH + UI =====\n'
for _ in $(seq 1 20); do
  if curl -fsS --max-time 3 http://127.0.0.1:8790/health; then echo; break; fi
  sleep 1
done
HEALTH=$(curl -fsS --max-time 3 http://127.0.0.1:8790/health)
python3 - "$HEALTH" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['status']=='ok'
assert j['runtime_controller']=='pi5'
assert j['git_controller']=='pi5'
assert j['ui']=='/'
print('AGENT_HEALTH=PASS')
print('RUNTIME_CONTROLLER='+j['runtime_controller'])
print('GIT_CONTROLLER='+j['git_controller'])
PY
curl -fsS --max-time 3 http://127.0.0.1:8790/ | grep -q 'LifeOS Autonomous Agent'
JOBS=$(curl -fsS --max-time 3 http://127.0.0.1:8790/jobs)
python3 - "$JOBS" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert isinstance(j.get('jobs'), list)
print('AGENT_UI=PASS')
print('JOB_LIST_API=PASS')
PY

printf '\n===== 5/7 — PRIVACY FAIL-CLOSED TEST =====\n'
PRIVATE_OUT=$(curl -fsS --max-time 60 -H 'Content-Type: application/json' \
  -d '{"request":"Read my private Paperless documents and summarize them"}' \
  http://127.0.0.1:8790/jobs)
python3 - "$PRIVATE_OUT" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
print('PRIVACY='+j['privacy'])
print('STATUS='+j['status'])
assert j['privacy']=='local-only'
assert j['status']=='BLOCKED'
assert not any('PI5_PATCH=APPLIED' in x.get('evidence','') for x in j.get('iterations',[]))
print('PRIVACY_BOUNDARY=PASS')
PY

printf '\n===== 6/7 — TRUE END-TO-END AUTONOMOUS SMOKE =====\n'
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
    print('ITERATION_'+str(x.get('iteration'))+'_BUILDER_RC='+str(x.get('builder_rc')))
    ev=str(x.get('evidence',''))
    if 'PI5_PATCH=APPLIED' in ev and 'PI5_PUSH=PASS' in ev:
        published=True
        print('PI5_GIT_PUBLICATION=PASS')
    if 'RUNTIME_LOOP_SMOKE=PASS' in ev and 'RUNTIME_RC=0' in ev:
        runtime=True
        print('PI5_RUNTIME_EVIDENCE=PASS')
    print('VERDICT='+str(x.get('verification',{}).get('verdict')))
if j['status'] != 'PASS':
    print('BLOCKED_REASON='+str(j.get('blocked_reason')))
    for x in j.get('iterations',[]):
        print('--- ITERATION '+str(x.get('iteration'))+' EVIDENCE TAIL ---')
        print(str(x.get('evidence',''))[-7000:])
        print('VERIFICATION='+json.dumps(x.get('verification',{}),sort_keys=True))
    raise SystemExit('AUTONOMOUS_E2E_SMOKE_DID_NOT_PASS')
assert published, 'missing Pi5-owned Git publication evidence'
assert runtime, 'missing Pi5 runtime evidence'
print('AUTONOMOUS_LOOP=PASS')
PY

printf '\n===== 7/7 — RESULT =====\n'
printf 'RESULT=PASS\n'
printf 'INPUT=natural_language_web_or_api\n'
printf 'CONTROLLER=Pi5\n'
printf 'GIT_PUBLISHER=Pi5\n'
printf 'RUNTIME_EXECUTOR=Pi5\n'
printf 'BUILDER=Engineer_Codex_cloud\n'
printf 'VERIFIER=TowerPC_Qwen_local\n'
printf 'ITERATES_TO=PASS_or_external_BLOCKED_or_8_iterations\n'
printf 'PRIVATE_DOCUMENTS_TO_CLOUD=blocked\n'
printf 'API=http://127.0.0.1:8790/jobs\n'
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [[ -n "${LAN_IP:-}" ]]; then
  printf 'UI=http://%s:8790/\n' "$LAN_IP"
else
  printf 'UI=http://Docker:8790/\n'
fi
printf 'Elapsed=%ss\n' "$(( $(date +%s)-START ))"
