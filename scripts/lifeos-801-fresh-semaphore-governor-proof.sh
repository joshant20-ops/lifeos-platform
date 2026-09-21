#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
ENV_FILE=/etc/lifeos/semaphore.env
SECRETS=/etc/lifeos/semaphore-secrets
ISSUE=862
REPO_FULL=joshant20-ops/lifeos-platform
GOV=http://127.0.0.1:8790
# #801 rerun trigger: cloud exhaustion now falls back to governed Tower Ollama
PROJECT_NAME='LifeOS 801 Acceptance'
TEMPLATE_NAME='801 post-migration intent'

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'RESULT=FAIL'; echo 'REASON=root_required'; exit 1; }
[[ -r "$ENV_FILE" ]] || { echo 'RESULT=FAIL'; echo 'REASON=semaphore_env_missing'; exit 1; }
for f in admin_user admin_password; do [[ -r "$SECRETS/$f" ]] || { echo "RESULT=FAIL"; echo "REASON=semaphore_secret_missing_$f"; exit 1; }; done
BIND_IP=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE")
BASE="http://${BIND_IP}:3000/api"
HEAD=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]]
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]]
[[ ! -e /var/lib/lifeos-backlog-runner/state.json ]]
[[ ! -e /etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf ]]
echo "801_FRESH_PROOF_HEAD=$HEAD"
echo '801_RETIRED_STATE_PRECHECK=PASS'

export LIFEOS_SEMAPHORE_BASE="$BASE" LIFEOS_SEMAPHORE_ADMIN_USER_FILE="$SECRETS/admin_user" LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE="$SECRETS/admin_password"
export LIFEOS_PLATFORM_HEAD="$HEAD" LIFEOS_PROJECT_NAME="$PROJECT_NAME" LIFEOS_TEMPLATE_NAME="$TEMPLATE_NAME"
TASK_META=$(mktemp); trap 'rm -f "$TASK_META"' EXIT
export LIFEOS_TASK_META="$TASK_META"
python3 - <<'PY'
import http.cookiejar,json,os,pathlib,time,urllib.request
base=os.environ['LIFEOS_SEMAPHORE_BASE'].rstrip('/')
login=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_USER_FILE']).read_text().strip()
password=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE']).read_text().strip()
project_name=os.environ['LIFEOS_PROJECT_NAME']; template_name=os.environ['LIFEOS_TEMPLATE_NAME']
jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def req(method,path,body=None,token=None,timeout=30):
    data=None if body is None else json.dumps(body).encode(); h={'Accept':'application/json'}
    if body is not None: h['Content-Type']='application/json'
    if token: h['Authorization']='Bearer '+token
    with opener.open(urllib.request.Request(base+path,data=data,headers=h,method=method),timeout=timeout) as r:
        raw=r.read(); return json.loads(raw) if raw and 'json' in r.headers.get('Content-Type','') else raw.decode(errors='replace')
req('POST','/auth/login',{'auth':login,'password':password})
tok=req('POST','/user/tokens'); token=tok['id']
try:
    projects=req('GET','/projects',token=token); p=next((x for x in projects if x.get('name')==project_name),None)
    if p is None:
        backup={'meta':{'name':project_name,'alert':False,'alert_chat':'','max_parallel_tasks':1,'type':''},
        'keys':[{'name':'None','type':'none'}],
        'repositories':[{'name':'LifeOS Platform Read Only','git_url':'/workspace/lifeos-platform','git_branch':'main','ssh_key':'None'}],
        'inventories':[{'name':'Localhost Read Only','inventory':'localhost ansible_connection=local','ssh_key':'None','become_key':'None','type':'static'}],
        'environments':[{'name':'Empty','password':None,'json':'{}','env':'{}'}],
        'views':[{'title':'Acceptance','position':0}],
        'templates':[{'inventory':'Localhost Read Only','repository':'LifeOS Platform Read Only','environment':'Empty','view':'Acceptance','name':template_name,
        'playbook':'orchestration/semaphore/playbooks/801-post-migration-intent.yml','arguments':'[]','allow_override_args_in_task':False,
        'description':'#801 bounded post-migration intent','app':'ansible','type':'','start_version':'','build_template':None,'autorun':False,'survey_vars':[],'suppress_success_alerts':True,'cron':''}]}
        req('POST','/projects/restore',backup,token=token); projects=req('GET','/projects',token=token); p=next(x for x in projects if x.get('name')==project_name)
    pid=int(p['id']); ts=req('GET',f'/project/{pid}/templates',token=token); t=next(x for x in ts if x.get('name')==template_name); tid=int(t['id'])
    task=req('POST',f'/project/{pid}/tasks',{'template_id':tid},token=token); task_id=int(task['id'])
    print(f'SEMAPHORE_TASK_ID={task_id}')
    terminal=None
    for _ in range(90):
        cur=req('GET',f'/project/{pid}/tasks/{task_id}',token=token); status=str(cur.get('status') or '').lower()
        if status in {'success','error','failed','stopped','canceled','cancelled'}: terminal=status; break
        time.sleep(2)
    if terminal!='success': raise RuntimeError(f'Semaphore terminal={terminal}')
    output=''
    for _ in range(16):
        output=req('GET',f'/project/{pid}/tasks/{task_id}/raw_output',token=token)
        if not isinstance(output,str): output=json.dumps(output)
        if 'LIFEOS_801_SEMAPHORE_INTENT=PASS issue=862 action=verify_governor_ots_boundary mutation=none' in output: break
        time.sleep(2)
    marker='LIFEOS_801_SEMAPHORE_INTENT=PASS issue=862 action=verify_governor_ots_boundary mutation=none'
    # Ansible/Semaphore may wrap a debug message at whitespace. Preserve an
    # exact semantic marker while normalising only transport whitespace/ANSI.
    import re
    normalised=re.sub(r'\\x1b\\[[0-9;]*m','',output)
    normalised=' '.join(normalised.split())
    if marker not in normalised:
        print('SEMAPHORE_RAW_OUTPUT_DIAGNOSTIC_BEGIN')
        print(output[-8000:])
        print('SEMAPHORE_RAW_OUTPUT_DIAGNOSTIC_END')
        try:
            structured=req('GET',f'/project/{pid}/tasks/{task_id}/output',token=token)
            print('SEMAPHORE_STRUCTURED_OUTPUT_DIAGNOSTIC='+json.dumps(structured,separators=(',',':'))[-8000:])
        except Exception as exc:
            print('SEMAPHORE_STRUCTURED_OUTPUT_DIAGNOSTIC_ERROR='+type(exc).__name__)
        raise RuntimeError('exact Semaphore intent marker absent')
    pathlib.Path(os.environ['LIFEOS_TASK_META']).write_text(json.dumps({'project_id':pid,'template_id':tid,'task_id':task_id,'status':terminal})+'\n')
    print('SEMAPHORE_TASK_TERMINAL=PASS'); print('SEMAPHORE_EXACT_INTENT=PASS')
finally:
    try: req('DELETE',f'/user/tokens/{token}',token=token)
    except Exception: pass
PY

# Semaphore owns the OTS execution decision; the host boundary performs the
# credential-free normal Governor submission only after exact intent validation.
# Governor already exposes its deterministic stuck-job classifier.  Stale
# persisted RUNNING records are observability/history, not live capacity, so
# exclude only IDs that Governor itself classifies as stuck.  Fresh active jobs
# continue to block this acceptance proof fail-closed.
ACTIVE=1
for idle_poll in $(seq 1 30); do
  ACTIVE=$(python3 - "$GOV" "$idle_poll" <<'PY'
import json,sys,urllib.request
base=sys.argv[1]
def get(path):
    with urllib.request.urlopen(base+path,timeout=10) as r: return json.load(r)
d=get('/jobs')
jobs=d.get('jobs',[]) if isinstance(d,dict) else d
stuck_payload=get('/jobs/stuck')
stuck_ids={str(j.get('id')) for j in (stuck_payload.get('stuck_jobs',[]) or []) if j.get('id')}
active=[j for j in jobs if str(j.get('status','')).upper() in {'QUEUED','RUNNING'} and str(j.get('id')) not in stuck_ids]
print(len(active))
for j in jobs:
    if str(j.get('status','')).upper() not in {'QUEUED','RUNNING'}: continue
    stale=str(j.get('id')) in stuck_ids
    print("GOVERNOR_ACTIVE_JOB id=%s status=%s stage=%s created=%s changed=%s deterministic_stuck=%s" % (
        j.get('id'),j.get('status'),j.get('stage'),j.get('created_at'),j.get('stage_changed_at'),str(stale).lower()
    ), file=sys.stderr)
PY
  )
  echo "GOVERNOR_IDLE_POLL=$idle_poll ACTIVE=$ACTIVE"
  [[ "$ACTIVE" == 0 ]] && break
  sleep 10
done
[[ "$ACTIVE" == 0 ]] || { echo "RESULT=RETRY"; echo "REASON=governor_busy_after_bounded_wait active=$ACTIVE"; exit 75; }
PROMPT='Acceptance fixture #862. Read-only task: verify docs/governor-ots-boundary.md exists in the canonical repository. Do not change files, services, configuration, credentials, GitHub issue state, or household state. Return evidence only.'
RESP=$(python3 - "$GOV" "$PROMPT" <<'PY'
import json,sys,urllib.request
body=json.dumps({'request':sys.argv[2]}).encode()
req=urllib.request.Request(sys.argv[1]+'/jobs?async=1',data=body,headers={'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(req,timeout=45) as r: print(json.dumps(json.load(r)))
PY
)
JOB_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("id",""))' "$RESP")
[[ -n "$JOB_ID" ]] || { echo 'RESULT=FAIL'; echo 'REASON=no_governor_job_id'; exit 1; }
echo "GOVERNOR_JOB_ID=$JOB_ID"
echo "801_DIAGNOSTIC_PRE_SUBMISSION_BEGIN"
echo "GOVERNOR_HEALTH=$(curl -fsS --max-time 10 "$GOV/health" || echo unavailable)"
echo "GOVERNOR_STUCK=$(curl -fsS --max-time 10 "$GOV/jobs/stuck" || echo unavailable)"
echo "CODEX_PATH=$(command -v codex || true)"
if command -v codex >/dev/null 2>&1; then
  echo "CODEX_VERSION=$(codex --version 2>&1 | head -1 || true)"
fi
echo "ENGINEER_HEALTH=$(curl -fsS --max-time 10 http://127.0.0.1:8793/health || echo unavailable)"
echo "801_DIAGNOSTIC_PRE_SUBMISSION_END"
runuser -u joshan -- gh issue comment "$ISSUE" --repo "$REPO_FULL" --body "### #801 post-migration live proof started
- Semaphore task: $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["task_id"])' "$TASK_META")
- Exact Semaphore intent: PASS
- Governor job: $JOB_ID
- Retired backlog state absent before submission: PASS" >/dev/null

STATUS=''
for n in $(seq 1 90); do
  STATUS=$(python3 - "$GOV" "$JOB_ID" <<'PY'
import json,sys,urllib.request
with urllib.request.urlopen(sys.argv[1]+'/jobs/'+sys.argv[2],timeout=10) as r: print(str(json.load(r).get('status') or ''))
PY
)
  echo "GOVERNOR_POLL=$n STATUS=$STATUS"
  case "$STATUS" in PASS|FAILED|BLOCKED) break;; esac
  sleep 5
done
if [[ "$STATUS" != PASS ]]; then
  echo "GOVERNOR_TERMINAL_DIAGNOSTIC_BEGIN"
  python3 - "$GOV" "$JOB_ID" <<'PY'
import json,sys,urllib.request
with urllib.request.urlopen(sys.argv[1]+'/jobs/'+sys.argv[2],timeout=10) as r:
    print(json.dumps(json.load(r),indent=2,sort_keys=True))
PY
  echo "GOVERNOR_TERMINAL_DIAGNOSTIC_END"
  echo "801_PROVIDER_DIAGNOSTIC_BEGIN"
  echo "ENGINEER_HEALTH=$(curl -fsS --max-time 10 http://127.0.0.1:8793/health || echo unavailable)"
  echo "CODEX_PATH=$(command -v codex || true)"
  if command -v codex >/dev/null 2>&1; then
    echo "CODEX_VERSION=$(codex --version 2>&1 | head -1 || true)"
  fi
  echo "GOVERNOR_STUCK=$(curl -fsS --max-time 10 "$GOV/jobs/stuck" || echo unavailable)"
  echo "NOTE=Provider stderr is preserved in GOVERNOR_TERMINAL_DIAGNOSTIC evidence above; usage-limit/provider-exhaustion is an external-capacity blocker, not an OTS migration failure."
  echo "801_PROVIDER_DIAGNOSTIC_END"
  echo "RESULT=FAIL"
  echo "REASON=governor_terminal_$STATUS"
  exit 1
fi
[[ ! -e /var/lib/lifeos-backlog-runner/state.json ]]
[[ ! -e /etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf ]]
runuser -u joshan -- gh issue comment "$ISSUE" --repo "$REPO_FULL" --body "### #801 post-migration live proof terminal
- Governor job: $JOB_ID
- Governor terminal: `PASS`
- Semaphore task terminal: `PASS`
- Retired backlog state recreated: `NO`
- Result: `PASS`" >/dev/null
echo 'POST_MIGRATION_RETIRED_STATE_ABSENT=PASS'
echo 'FRESH_SEMAPHORE_TO_GOVERNOR_TERMINAL=PASS'
echo "FRESH_GOVERNOR_JOB_ID=$JOB_ID"
echo 'RESULT=PASS'
