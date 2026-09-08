#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
REPO=/home/joshan/lifeos-platform
AGENT_CORE="$REPO/governor/autonomous_agent.py"
AGENT_SERVER="$REPO/governor/autonomous_agent_server.py"
AI_BROKER="$REPO/governor/ai_broker.py"
JOB_RECORDS="$REPO/governor/job_records.py"
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

printf '===== 1/8 — SOURCE VERIFY =====\n'
git -C "$REPO" fetch origin main
if [[ -n "$(git -C "$REPO" status --porcelain --untracked-files=all)" ]]; then
  printf 'RESULT=BLOCKED\nREASON=canonical_checkout_dirty\n'
  git -C "$REPO" status --short
  exit 20
fi
HEAD_SHA=$(git -C "$REPO" rev-parse HEAD)
ORIGIN_SHA=$(git -C "$REPO" rev-parse origin/main)
if [[ "$HEAD_SHA" != "$ORIGIN_SHA" ]]; then
  printf 'RESULT=BLOCKED\nREASON=canonical_checkout_not_at_origin_main\n'
  printf 'HEAD=%s\nORIGIN_MAIN=%s\n' "$HEAD_SHA" "$ORIGIN_SHA"
  exit 20
fi
printf 'CANONICAL_SOURCE=PASS\nHEAD=%s\n' "${HEAD_SHA:0:7}"

printf '\n===== 2/8 — PREFLIGHT =====\n'
python3 -m py_compile "$AGENT_CORE" "$AGENT_SERVER" "$AI_BROKER" "$JOB_RECORDS"
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
sudo install -m 0644 "$JOB_RECORDS" /usr/local/libexec/job_records.py
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
code=$(curl -sS -o "$TMPDIR/broker-unauth.json" -w '%{http_code}' --max-time 10 \
  -H 'Content-Type: application/json' \
  -d '{"model":"lifeos-normal","messages":[{"role":"user","content":"test"}]}' \
  http://127.0.0.1:8790/v1/chat/completions)
test "$code" = 401
printf 'BROKER_UNAUTHENTICATED_REJECT=PASS\n'
BROKER_REQ=$(python3 - <<'PY'
import json
print(json.dumps({
    "model": "lifeos-engineering-normal",
    "messages": [{
        "role": "user",
        "content": "Call report_test_value with value GOVERNOR_LOCAL_TOOL_OK. Do not answer normally."
    }],
    "tools": [{
        "type": "function",
        "function": {
            "name": "report_test_value",
            "description": "Report a harmless deployment test value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"]
            }
        }
    }],
    "tool_choice": "required"
}))
PY
)
BROKER_OUT=$(curl -fsS --max-time 180 \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $(cat "$BROKER_TOKEN")" \
  -d "$BROKER_REQ" http://127.0.0.1:8790/v1/chat/completions)
python3 - "$BROKER_OUT" <<'PY'
import json,sys
j=json.loads(sys.argv[1])
assert j['lifeos_privacy']=='normal', j
assert j['lifeos_provider']=='ollama', j
choice=j['choices'][0]
assert choice['finish_reason']=='tool_calls', choice
calls=choice['message'].get('tool_calls') or []
match=None
for call in calls:
    fn=call.get('function') or {}
    if fn.get('name') != 'report_test_value':
        continue
    args=fn.get('arguments') or '{}'
    if isinstance(args,str):
        args=json.loads(args)
    if args.get('value') == 'GOVERNOR_LOCAL_TOOL_OK':
        match=call
        break
assert match is not None, calls
print('BROKER_AUTHENTICATED_LOCAL_TOOL_CALL=PASS')
print('BROKER_PROVIDER=ollama')
PY

printf '\n===== 6/8 — UI + PRIVACY FAIL-CLOSED =====\n'
curl -fsS --max-time 3 http://127.0.0.1:8790/ | grep -q 'LifeOS Autonomous Agent'
JOBS_FILE="$TMPDIR/jobs.json"
curl -fsS --max-time 10 -o "$JOBS_FILE" http://127.0.0.1:8790/jobs
python3 - "$JOBS_FILE" <<'PY'
import json,pathlib,sys
j=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert isinstance(j.get('jobs'), list)
print('AGENT_UI=PASS')
print('JOB_LIST_API=PASS')
PY
PRIVATE_FILE="$TMPDIR/private-job.json"
curl -fsS --max-time 60 -H 'Content-Type: application/json' \
  -d '{"request":"Summarize upcoming appointments","privacy_domain":"personal-administration"}' \
  -o "$PRIVATE_FILE" http://127.0.0.1:8790/jobs
python3 - "$PRIVATE_FILE" <<'PY'
import json,pathlib,sys
j=json.loads(pathlib.Path(sys.argv[1]).read_text())
assert j['privacy']=='local-only'
assert j['privacy_domain']=='personal-administration'
assert j['status']=='BLOCKED'
assert j.get('record_publication',{}).get('state')=='STAGED'
assert not any('PI5_PATCH=APPLIED' in x.get('evidence','') for x in j.get('iterations',[]))
print('PRIVACY_BOUNDARY=PASS')
print('JOB_RECORD_RUNTIME_STAGE=PASS')
PY

printf '\n===== 7/8 — TRUE END-TO-END AUTONOMOUS SMOKE =====\n'
if [[ "${LIFEOS_SKIP_AUTONOMOUS_E2E:-0}" == "1" ]]; then
  printf 'AUTONOMOUS_E2E=SKIPPED_OPENHANDS_GATE\n'
else
SMOKE_REQ='Prove the LifeOS autonomous runtime loop works. In your disposable Engineer worktree, create the required per-job Pi5 runtime launcher but do not commit or push it yourself; Pi5 owns Git publication. The launcher must safely and read-only curl http://127.0.0.1:8790/health from Pi5, verify service=lifeos-autonomous-agent, status=ok, runtime_controller=pi5, git_controller=pi5, print RUNTIME_LOOP_SMOKE=PASS, and make no other system changes. Run focused tests and leave the launcher in the worktree for automatic handoff. Unrelated repository failures are not blockers.'
SMOKE_JSON=$(python3 - "$SMOKE_REQ" <<'PY'
import json,sys
print(json.dumps({'request':sys.argv[1]}))
PY
)
SMOKE_FILE="$TMPDIR/e2e-smoke.json"
curl -fsS --max-time 1100 -H 'Content-Type: application/json' \
  -d "$SMOKE_JSON" -o "$SMOKE_FILE" http://127.0.0.1:8790/jobs
python3 - "$SMOKE_FILE" <<'PY'
import importlib.util
import json
import pathlib
import sys

j=json.loads(pathlib.Path(sys.argv[1]).read_text())
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
    spec=importlib.util.spec_from_file_location('lifeos_job_records', pathlib.Path('/usr/local/libexec/job_records.py'))
    records=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(records)
    for index, iteration in enumerate(j.get('iterations',[]), start=1):
        safe=records.sanitise({
            'stage': iteration.get('stage'),
            'failure_signature': iteration.get('failure_signature'),
            'evidence': str(iteration.get('evidence') or '')[:1200],
        })
        rendered=json.dumps(safe, sort_keys=True, ensure_ascii=True)
        print(f'ITERATION_{index}_SUMMARY='+rendered[:1800])
    raise SystemExit('AUTONOMOUS_E2E_SMOKE_DID_NOT_PASS')
assert published, 'missing Pi5-owned Git publication evidence'
assert runtime, 'missing Pi5 runtime evidence'
print('AUTONOMOUS_LOOP=PASS')
PY

fi
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
