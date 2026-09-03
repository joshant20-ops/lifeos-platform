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

[[ $EUID -eq 0 ]] || { echo 'ERROR: run via sudo'; exit 1; }
[[ -r "$ENV_FILE" ]] || { echo 'ERROR: Semaphore env missing'; exit 1; }
for f in admin_user admin_password; do [[ -r "$SECRETS/$f" ]] || { echo "ERROR: missing secret $f"; exit 1; }; done

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

printf '%s\n' 'SEMAPHORE_DISPATCH_FIXTURE_PROOF_VERSION=1'
printf '%s\n' 'MUTATIONS=LOCAL_SYNTHETIC_SHADOW_STATE_AND_SEMAPHORE_TASK_HISTORY_ONLY'
echo "platform_head=$HEAD_BEFORE"
echo "semaphore_base=$BASE"
curl -fsS --max-time 5 "$BASE/ping" >/dev/null || { echo 'ERROR: Semaphore API unavailable'; exit 1; }

install -d -o root -g root -m 0755 "$SHADOW_ROOT" "$INPUT_DIR"

export LIFEOS_SEMAPHORE_BASE="$BASE"
export LIFEOS_SEMAPHORE_ADMIN_USER_FILE="$SECRETS/admin_user"
export LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE="$SECRETS/admin_password"
export LIFEOS_SEMAPHORE_PROJECT_NAME="$PROJECT_NAME"
export LIFEOS_SEMAPHORE_TEMPLATE_NAME="$TEMPLATE_NAME"
export LIFEOS_PLATFORM="$PLATFORM"
export LIFEOS_FIXTURE_SNAPSHOT="$SNAPSHOT"

python3 - <<'PY'
import http.cookiejar, importlib.util, json, os, pathlib, re, sys, time, urllib.error, urllib.request

base=os.environ['LIFEOS_SEMAPHORE_BASE'].rstrip('/')
login=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_USER_FILE']).read_text().strip()
password=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE']).read_text().strip()
project_name=os.environ['LIFEOS_SEMAPHORE_PROJECT_NAME']
template_name=os.environ['LIFEOS_SEMAPHORE_TEMPLATE_NAME']
platform=pathlib.Path(os.environ['LIFEOS_PLATFORM'])
snapshot_path=pathlib.Path(os.environ['LIFEOS_FIXTURE_SNAPSHOT'])

spec=importlib.util.spec_from_file_location('lifeos_backlog_runner', platform/'governor/backlog_runner.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

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

request('POST','/auth/login',{'auth':login,'password':password})
tok=request('POST','/user/tokens'); token=tok.get('id') if isinstance(tok,dict) else None
if not token: raise RuntimeError('Semaphore token creation returned no id')

fixtures=[
    {
        'name':'normal-planning',
        'snapshot':{
            'timestamp':2000000000,
            'issues':[{'number':9101,'title':'P2 synthetic normal planning','created_at':'2026-01-01T00:00:00Z','labels':[{'name':'lifeos-engineer-ready'},{'name':'risk:normal'}]}],
            'state':{'issues':{}}
        },
        'expected':('9101','planning','normal','none'),
    },
    {
        'name':'local-planning',
        'snapshot':{
            'timestamp':2000000000,
            'issues':[{'number':9102,'title':'P2 synthetic local planning','created_at':'2026-01-01T00:00:00Z','labels':[{'name':'lifeos-engineer-ready'},{'name':'risk:local-only'}]}],
            'state':{'issues':{}}
        },
        'expected':('9102','planning','local','none'),
    },
    {
        'name':'recovery-target',
        'snapshot':{
            'timestamp':2000000000,
            'issues':[{'number':9103,'title':'P2 synthetic recovery target','created_at':'2026-01-01T00:00:00Z','labels':[{'name':'lifeos-engineer-ready'},{'name':'risk:normal'}]}],
            'state':{'issues':{'9103':{'work_state':'IN_PROGRESS','retry_after':None,'plan':{
                'schema_version':1,'issue':9103,'revision':1,'state':'IN_PROGRESS','created_at':'2026-01-01T00:00:00Z',
                'milestones':[{'id':'m1','title':'Synthetic milestone','mandatory':True,'verification':'fixture','state':'IN_PROGRESS','targets':[
                    {'id':'t-recover','title':'Synthetic failed target','state':'FAILED','mandatory':True,'depends_on':[],
                     'acceptance_criteria':['fixture only'],'runtime_verification_required':False,'attempts':1,'evidence':[{'summary':'synthetic failure'}]}
                ]}]
            }}}}
        },
        'expected':('9103','recovery','normal','t-recover'),
    },
]

try:
    projects=request('GET','/projects',token=token); project=next((p for p in projects if p.get('name')==project_name),None)
    if project is None: raise RuntimeError('LifeOS Dispatch Shadow project missing; run live dispatch shadow proof first')
    pid=int(project['id']); templates=request('GET',f'/project/{pid}/templates',token=token); template=next((t for t in templates if t.get('name')==template_name),None)
    if template is None: raise RuntimeError('Backlog dispatch shadow template missing')
    tid=int(template['id']); print(f'PROJECT_ID={pid}'); print(f'TEMPLATE_ID={tid}')

    marker_re=re.compile(r'LIFEOS_SEMAPHORE_DISPATCH_SHADOW=PASS dispatch=([^ ]+) issue=([^ ]+) phase=([^ ]+) builder=([^ ]+) target_id=([^ ]+) candidate_count=(\d+) mutation=none')

    for fixture in fixtures:
        payload=fixture['snapshot']
        tmp=snapshot_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload,sort_keys=True)+'\n'); os.chmod(tmp,0o444); os.replace(tmp,snapshot_path); os.chown(snapshot_path,0,0)

        issue=mod.choose_issue(payload['issues'],payload['state'],payload['timestamp'])
        if issue is None:
            canonical=('none','none','none','none')
        else:
            number=int(issue['number']); entry=payload['state'].get('issues',{}).get(str(number),{}); plan=entry.get('plan'); target=mod.next_target(plan) if plan else None
            if not plan: phase, target_id='planning','none'
            elif target and target.get('state') in {'FAILED','BLOCKED'}: phase,target_id='recovery',str(target.get('id') or 'none')
            elif target: phase,target_id='target',str(target.get('id') or 'none')
            else: phase,target_id='blocked-no-target','none'
            canonical=(str(number),phase,'local' if mod.private_issue(issue) else 'normal',target_id)
        if canonical != fixture['expected']:
            raise RuntimeError(f"fixture {fixture['name']} canonical mismatch expected={fixture['expected']} actual={canonical}")

        task=request('POST',f'/project/{pid}/tasks',{'template_id':tid},token=token,timeout=30); task_id=int(task['id'])
        terminal=None
        for _ in range(90):
            final=request('GET',f'/project/{pid}/tasks/{task_id}',token=token); status=str(final.get('status') or '').lower()
            if status in {'success','error','failed','stopped','canceled','cancelled'}: terminal=status; break
            time.sleep(2)
        if terminal!='success':
            out=request('GET',f'/project/{pid}/tasks/{task_id}/raw_output',token=token,timeout=30); print(str(out)[-4000:]); raise RuntimeError(f"fixture {fixture['name']} task status={terminal}")
        marker=None; output=''; deadline=time.time()+30
        while time.time()<deadline:
            output=request('GET',f'/project/{pid}/tasks/{task_id}/raw_output',token=token,timeout=30); output=output if isinstance(output,str) else json.dumps(output,separators=(',',':'))
            marker=marker_re.search(output)
            if marker: break
            time.sleep(1)
        if marker is None: raise RuntimeError(f"fixture {fixture['name']} PASS marker absent")
        actual=(marker.group(2),marker.group(3),marker.group(4),marker.group(5))
        if actual != canonical:
            raise RuntimeError(f"fixture {fixture['name']} dispatch mismatch canonical={canonical} semaphore={actual}")
        print(f"FIXTURE={fixture['name']} TASK_ID={task_id} ISSUE={actual[0]} PHASE={actual[1]} BUILDER={actual[2]} TARGET={actual[3]} PARITY=PASS")

    print('NONEMPTY_DISPATCH_PARITY=PASS')
    print('NORMAL_ROUTE=PASS')
    print('LOCAL_ONLY_ROUTE=PASS')
    print('RECOVERY_ROUTE=PASS')
    print('AUTHORITATIVE_SUBMISSION=NONE')
finally:
    if token:
        try: request('DELETE',f'/user/tokens/{token}',token=token); print('TEMP_API_TOKEN_REVOKED=YES')
        except Exception as exc: print(f'TEMP_API_TOKEN_REVOKED=ERROR:{type(exc).__name__}',file=sys.stderr)
PY

HEAD_AFTER=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
INDEX_OWNER_AFTER=$(stat -c '%U:%G' "$PLATFORM/.git/index")
UNITS_AFTER=$(snapshot_units)
[[ "$HEAD_AFTER" == "$HEAD_BEFORE" ]] || { echo 'ERROR: platform HEAD changed'; exit 1; }
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform working tree changed'; exit 1; }
[[ "$INDEX_OWNER_AFTER" == "$INDEX_OWNER_BEFORE" ]] || { echo 'ERROR: git metadata ownership changed'; exit 1; }
[[ "$UNITS_AFTER" == "$UNITS_BEFORE" ]] || { echo 'ERROR: custom execution unit state changed'; exit 1; }

echo
echo 'RESULT=PASS'
echo 'SEMAPHORE_SYNTHETIC_NONEMPTY_DISPATCH=PASS'
echo 'NONEMPTY_DISPATCH_PARITY=PASS'
echo 'NORMAL_ROUTE=PASS'
echo 'LOCAL_ONLY_ROUTE=PASS'
echo 'RECOVERY_ROUTE=PASS'
echo 'AUTHORITATIVE_SUBMISSION=NONE'
echo 'GITHUB_MUTATION=NONE'
echo 'PLATFORM_MUTATION=NONE'
echo 'CUSTOM_EXECUTION_PATH_CHANGED=NO'
echo 'NEXT_ACTION=design_single_gated_real_submission_with_automatic_rollback_to_legacy_dispatcher'
