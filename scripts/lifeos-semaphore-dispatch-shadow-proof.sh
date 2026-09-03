#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
ENV_FILE=/etc/lifeos/semaphore.env
SECRETS=/etc/lifeos/semaphore-secrets
SHADOW_ROOT=/var/lib/lifeos-semaphore-shadow
INPUT_DIR=$SHADOW_ROOT/input
SNAPSHOT=$INPUT_DIR/backlog-dispatch.json
PROJECT_NAME='LifeOS Dispatch Shadow'
TEMPLATE_NAME='Backlog dispatch shadow'
REPO_FULL='joshant20-ops/lifeos-platform'

[[ $EUID -eq 0 ]] || { echo 'ERROR: run via sudo'; exit 1; }
[[ -r "$ENV_FILE" ]] || { echo 'ERROR: Semaphore env missing'; exit 1; }
for f in admin_user admin_password; do [[ -r "$SECRETS/$f" ]] || { echo "ERROR: missing secret $f"; exit 1; }; done
[[ -r /var/lib/lifeos-backlog-runner/state.json ]] || { echo 'ERROR: backlog state missing'; exit 1; }

BIND_IP=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE")
[[ -n "$BIND_IP" ]] || { echo 'ERROR: Semaphore bind IP missing'; exit 1; }
BASE="http://${BIND_IP}:3000/api"

HEAD_BEFORE=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
INDEX_OWNER_BEFORE=$(stat -c '%U:%G' "$PLATFORM/.git/index")

units=(
  lifeos-backlog-runner.timer
  lifeos-engineer-dispatcher.timer
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
)
snapshot_units() {
  local u
  for u in "${units[@]}"; do
    printf '%s=%s/%s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || true)" "$(systemctl is-enabled "$u" 2>/dev/null || true)"
  done
}
UNITS_BEFORE=$(snapshot_units)

printf '%s\n' 'SEMAPHORE_DISPATCH_SHADOW_PROOF_VERSION=1'
printf '%s\n' 'MUTATIONS=LOCAL_SHADOW_STATE_AND_SEMAPHORE_CATALOGUE_ONLY'
echo "platform_head=$HEAD_BEFORE"
echo "semaphore_base=$BASE"
curl -fsS --max-time 5 "$BASE/ping" >/dev/null || { echo 'ERROR: Semaphore API unavailable'; exit 1; }

install -d -o root -g root -m 0755 "$SHADOW_ROOT" "$INPUT_DIR"
TMP_ISSUES=$(mktemp)
trap 'rm -f "$TMP_ISSUES"' EXIT
printf '[]\n' >"$TMP_ISSUES"
page=1
while :; do
  PAGE_FILE=$(mktemp)
  runuser -u joshan -- gh api "repos/$REPO_FULL/issues?state=open&per_page=100&page=$page" >"$PAGE_FILE"
  COUNT=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$PAGE_FILE")
  python3 - "$TMP_ISSUES" "$PAGE_FILE" <<'PY'
import json, pathlib, sys
out, page = map(pathlib.Path, sys.argv[1:])
a = json.loads(out.read_text()); b = json.loads(page.read_text())
out.write_text(json.dumps(a + b) + '\n')
PY
  rm -f "$PAGE_FILE"
  (( COUNT < 100 )) && break
  ((page++))
done

SNAPSHOT="$SNAPSHOT" TMP_ISSUES="$TMP_ISSUES" python3 - <<'PY'
import json, os, pathlib, time
raw = json.loads(pathlib.Path(os.environ['TMP_ISSUES']).read_text())
issues = []
for item in raw:
    if 'pull_request' in item:
        continue
    issues.append({
        'number': int(item['number']),
        'title': str(item.get('title') or ''),
        'created_at': str(item.get('created_at') or ''),
        'labels': [{'name': str(x.get('name') or '')} for x in item.get('labels', [])],
    })
state_raw = json.loads(pathlib.Path('/var/lib/lifeos-backlog-runner/state.json').read_text())
state = {'issues': {}}
for number, entry in state_raw.get('issues', {}).items():
    if not isinstance(entry, dict):
        continue
    state['issues'][str(number)] = {
        'work_state': entry.get('work_state'),
        'retry_after': entry.get('retry_after'),
        'plan': entry.get('plan'),
    }
payload = {'timestamp': int(time.time()), 'issues': issues, 'state': state}
p = pathlib.Path(os.environ['SNAPSHOT']); tmp = p.with_suffix('.tmp')
tmp.write_text(json.dumps(payload, sort_keys=True) + '\n'); tmp.chmod(0o444); tmp.replace(p)
PY
chown root:root "$SNAPSHOT"; chmod 0444 "$SNAPSHOT"
echo "SNAPSHOT_ISSUES=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["issues"]))' "$SNAPSHOT")"

EXPECTED=$(PLATFORM="$PLATFORM" SNAPSHOT="$SNAPSHOT" python3 - <<'PY'
import importlib.util, json, os
spec = importlib.util.spec_from_file_location('lifeos_backlog_runner', os.path.join(os.environ['PLATFORM'], 'governor/backlog_runner.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
data = json.load(open(os.environ['SNAPSHOT']))
issue = mod.choose_issue(data['issues'], data['state'], data['timestamp'])
if issue is None:
    print('none|none|none|none')
    raise SystemExit
number = int(issue['number']); entry = data['state'].get('issues', {}).get(str(number), {})
plan = entry.get('plan'); target = mod.next_target(plan) if plan else None
if not plan:
    phase, tid = 'planning', 'none'
elif target and target.get('state') in {'FAILED','BLOCKED'}:
    phase, tid = 'recovery', str(target.get('id') or 'none')
elif target:
    phase, tid = 'target', str(target.get('id') or 'none')
else:
    phase, tid = 'blocked-no-target', 'none'
builder = 'local' if mod.private_issue(issue) else 'normal'
print(f'{number}|{phase}|{builder}|{tid}')
PY
)
IFS='|' read -r EXPECTED_ISSUE EXPECTED_PHASE EXPECTED_BUILDER EXPECTED_TARGET <<<"$EXPECTED"
echo "CANONICAL_DISPATCH_ISSUE=$EXPECTED_ISSUE"
echo "CANONICAL_DISPATCH_PHASE=$EXPECTED_PHASE"
echo "CANONICAL_DISPATCH_BUILDER=$EXPECTED_BUILDER"
echo "CANONICAL_DISPATCH_TARGET=$EXPECTED_TARGET"

export LIFEOS_SEMAPHORE_BASE="$BASE" LIFEOS_SEMAPHORE_ADMIN_USER_FILE="$SECRETS/admin_user" LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE="$SECRETS/admin_password"
export LIFEOS_SEMAPHORE_PROJECT_NAME="$PROJECT_NAME" LIFEOS_SEMAPHORE_TEMPLATE_NAME="$TEMPLATE_NAME"
export LIFEOS_EXPECTED_ISSUE="$EXPECTED_ISSUE" LIFEOS_EXPECTED_PHASE="$EXPECTED_PHASE" LIFEOS_EXPECTED_BUILDER="$EXPECTED_BUILDER" LIFEOS_EXPECTED_TARGET="$EXPECTED_TARGET"

python3 - <<'PY'
import http.cookiejar, json, os, pathlib, re, sys, time, urllib.error, urllib.request
base=os.environ['LIFEOS_SEMAPHORE_BASE'].rstrip('/')
login=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_USER_FILE']).read_text().strip(); password=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE']).read_text().strip()
project_name=os.environ['LIFEOS_SEMAPHORE_PROJECT_NAME']; template_name=os.environ['LIFEOS_SEMAPHORE_TEMPLATE_NAME']
expected=(os.environ['LIFEOS_EXPECTED_ISSUE'],os.environ['LIFEOS_EXPECTED_PHASE'],os.environ['LIFEOS_EXPECTED_BUILDER'],os.environ['LIFEOS_EXPECTED_TARGET'])
jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def request(method,path,body=None,token=None,timeout=15):
    data=None if body is None else json.dumps(body).encode(); headers={'Accept':'application/json'}
    if body is not None: headers['Content-Type']='application/json'
    if token: headers['Authorization']=f'Bearer {token}'
    req=urllib.request.Request(base+path,data=data,headers=headers,method=method)
    try:
        with opener.open(req,timeout=timeout) as r:
            raw=r.read(); ctype=r.headers.get('Content-Type','')
            return json.loads(raw) if 'json' in ctype and raw else raw.decode(errors='replace')
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'{method} {path} HTTP {exc.code}: {exc.read().decode(errors="replace")[:1200]}') from exc
request('POST','/auth/login',{'auth':login,'password':password}); tok=request('POST','/user/tokens'); token=tok.get('id') if isinstance(tok,dict) else None
if not token: raise RuntimeError('Semaphore token creation returned no id')
try:
    projects=request('GET','/projects',token=token); project=next((p for p in projects if p.get('name')==project_name),None)
    if project is None:
        backup={'meta':{'name':project_name,'alert':False,'alert_chat':'','max_parallel_tasks':1,'type':''},'keys':[{'name':'None','type':'none'}],
        'repositories':[{'name':'LifeOS Platform Read Only','git_url':'/workspace/lifeos-platform','git_branch':'main','ssh_key':'None'}],
        'inventories':[{'name':'Localhost Read Only','inventory':'localhost ansible_connection=local','ssh_key':'None','become_key':'None','type':'static'}],
        'environments':[{'name':'Empty','password':None,'json':'{}','env':'{}'}],'views':[{'title':'Shadow','position':0}],
        'templates':[{'inventory':'Localhost Read Only','repository':'LifeOS Platform Read Only','environment':'Empty','view':'Shadow','name':template_name,
        'playbook':'orchestration/semaphore/playbooks/backlog-shadow-dispatch.yml','arguments':'[]','allow_override_args_in_task':False,
        'description':'Non-authoritative dispatch-intent shadow for LifeOS backlog work','app':'ansible','type':'','start_version':'','build_template':None,'autorun':False,'survey_vars':[],'suppress_success_alerts':True,'cron':''}]}
        request('POST','/projects/restore',backup,token=token,timeout=30); projects=request('GET','/projects',token=token); project=next(p for p in projects if p.get('name')==project_name); print(f'PROJECT_STATE=CREATED id={project["id"]}')
    else: print(f'PROJECT_STATE=REUSED id={project["id"]}')
    pid=int(project['id']); templates=request('GET',f'/project/{pid}/templates',token=token); template=next((t for t in templates if t.get('name')==template_name),None)
    if template is None: raise RuntimeError('dispatch shadow template missing')
    tid=int(template['id']); print(f'TEMPLATE_ID={tid}')
    task=request('POST',f'/project/{pid}/tasks',{'template_id':tid},token=token,timeout=30); task_id=int(task['id']); print(f'TASK_ID={task_id}')
    terminal=None
    for _ in range(90):
        final=request('GET',f'/project/{pid}/tasks/{task_id}',token=token); status=str(final.get('status') or '').lower()
        if status in {'success','error','failed','stopped','canceled','cancelled'}: terminal=status; break
        time.sleep(2)
    if terminal is None: raise RuntimeError('Semaphore dispatch shadow task timed out')
    print(f'TASK_STATUS={terminal}')
    if terminal!='success':
        print(str(request('GET',f'/project/{pid}/tasks/{task_id}/raw_output',token=token,timeout=30))[-4000:]); raise RuntimeError(f'dispatch shadow task status={terminal}')
    marker=None; output=''; deadline=time.time()+30
    pat=re.compile(r'LIFEOS_SEMAPHORE_DISPATCH_SHADOW=PASS dispatch=([^ ]+) issue=([^ ]+) phase=([^ ]+) builder=([^ ]+) target_id=([^ ]+) candidate_count=(\d+) mutation=none')
    while time.time()<deadline:
        output=request('GET',f'/project/{pid}/tasks/{task_id}/raw_output',token=token,timeout=30); output=output if isinstance(output,str) else json.dumps(output,separators=(',',':'))
        marker=pat.search(output)
        if marker: break
        time.sleep(1)
    if marker is None: print(output[-4000:]); raise RuntimeError('dispatch shadow PASS marker absent')
    actual=(marker.group(2),marker.group(3),marker.group(4),marker.group(5))
    print(f'SEMAPHORE_DISPATCH={marker.group(1)}'); print(f'SEMAPHORE_DISPATCH_ISSUE={actual[0]}'); print(f'SEMAPHORE_DISPATCH_PHASE={actual[1]}'); print(f'SEMAPHORE_DISPATCH_BUILDER={actual[2]}'); print(f'SEMAPHORE_DISPATCH_TARGET={actual[3]}')
    if actual!=expected: raise RuntimeError(f'dispatch mismatch canonical={expected} semaphore={actual}')
    print('DISPATCH_INTENT_PARITY=PASS'); print('AUTHORITATIVE_SUBMISSION=NONE'); print('RESULT_PROPAGATION=PASS')
finally:
    if token:
        try: request('DELETE',f'/user/tokens/{token}',token=token); print('TEMP_API_TOKEN_REVOKED=YES')
        except Exception as exc: print(f'TEMP_API_TOKEN_REVOKED=ERROR:{type(exc).__name__}',file=sys.stderr)
PY

HEAD_AFTER=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD); INDEX_OWNER_AFTER=$(stat -c '%U:%G' "$PLATFORM/.git/index"); UNITS_AFTER=$(snapshot_units)
[[ "$HEAD_AFTER" == "$HEAD_BEFORE" ]] || { echo 'ERROR: platform HEAD changed'; exit 1; }
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform working tree changed'; exit 1; }
[[ "$INDEX_OWNER_AFTER" == "$INDEX_OWNER_BEFORE" ]] || { echo 'ERROR: git metadata ownership changed'; exit 1; }
[[ "$UNITS_AFTER" == "$UNITS_BEFORE" ]] || { echo 'ERROR: custom execution unit state changed'; exit 1; }

echo
echo 'RESULT=PASS'
echo 'SEMAPHORE_DISPATCH_SHADOW=PASS'
echo 'DISPATCH_INTENT_PARITY=PASS'
echo 'AUTHORITATIVE_SUBMISSION=NONE'
echo 'GITHUB_MUTATION=NONE'
echo 'PLATFORM_MUTATION=NONE'
echo 'CUSTOM_EXECUTION_PATH_CHANGED=NO'
echo 'NEXT_ACTION=run_shadow_dispatch_when_an_eligible_issue_exists_then_enable_single_gated_submission'
