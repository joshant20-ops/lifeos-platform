#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
STATE=/var/lib/lifeos-backlog-runner/state.json
TOKEN=/etc/lifeos/backlog-dispatcher.token
REPO_FULL=joshant20-ops/lifeos-platform
GOV=http://127.0.0.1:8790
MODE=${1:---check}

[[ $EUID -eq 0 ]] || { echo 'ERROR: run via sudo'; exit 1; }
[[ "$MODE" == "--check" || "$MODE" == "--execute" ]] || { echo 'usage: lifeos-semaphore-single-gated-submission.sh [--check|--execute]'; exit 2; }
[[ -r "$STATE" ]] || { echo 'ERROR: backlog state missing'; exit 1; }
[[ -r "$TOKEN" ]] || { echo 'ERROR: backlog dispatcher token missing'; exit 1; }
[[ -d "$PLATFORM/.git" ]] || { echo 'ERROR: platform repository missing'; exit 1; }

HEAD=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || { echo 'ERROR: platform HEAD is not origin/main'; exit 1; }
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository dirty'; exit 1; }
[[ "$(stat -c '%U:%G' "$PLATFORM/.git/index")" == 'joshan:joshan' ]] || { echo 'ERROR: git metadata ownership invalid'; exit 1; }

printf '%s\n' 'SEMAPHORE_SINGLE_GATED_SUBMISSION_VERSION=2'
printf 'MODE=%s\n' "$MODE"
printf 'PLATFORM_HEAD=%s\n' "$HEAD"
printf '%s\n' 'AUTHORITY_MODEL=SEMAPHORE_INTENT_HOST_VALIDATION_GOVERNOR_SUBMISSION'
printf '%s\n' 'GOVERNOR_CREDENTIAL_IN_SEMAPHORE=NO'

[[ "$(systemctl is-active lifeos-backlog-runner.service 2>/dev/null || true)" != active ]] || { echo 'ERROR: legacy backlog runner service currently active'; exit 1; }

ACTIVE_GOV=$(python3 - "$GOV" <<'PY'
import json,sys,urllib.request
base=sys.argv[1]
with urllib.request.urlopen(base+'/jobs',timeout=10) as r: data=json.load(r)
if isinstance(data,dict): data=data.get('jobs',data.get('items',[]))
active=[j for j in data if str(j.get('status','')).upper() in {'QUEUED','RUNNING'}]
print(len(active))
PY
)
[[ "$ACTIVE_GOV" == 0 ]] || { echo "ERROR: governor already has active jobs count=$ACTIVE_GOV"; exit 1; }

TMP=$(mktemp -d)
chown joshan:joshan "$TMP"
chmod 0700 "$TMP"
trap 'rm -rf "$TMP"' EXIT
ISSUES=$TMP/issues.json
PLAN=$TMP/plan.json
runuser -u joshan -- sh -c 'printf "[]\n" > "$1"' sh "$ISSUES"
page=1
while :; do
  PAGE=$TMP/page.json
  runuser -u joshan -- gh api "repos/$REPO_FULL/issues?state=open&per_page=100&page=$page" >"$PAGE"
  chown joshan:joshan "$PAGE"
  chmod 0600 "$PAGE"
  COUNT=$(runuser -u joshan -- python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$PAGE")
  runuser -u joshan -- python3 - "$ISSUES" "$PAGE" <<'PY'
import json,pathlib,sys
out,page=map(pathlib.Path,sys.argv[1:])
a=json.loads(out.read_text()); b=json.loads(page.read_text())
out.write_text(json.dumps(a+b)+'\n')
PY
  (( COUNT < 100 )) && break
  ((page++))
done

PLATFORM="$PLATFORM" STATE="$STATE" ISSUES="$ISSUES" PLAN="$PLAN" runuser -u joshan -- env \
  PLATFORM="$PLATFORM" STATE="$STATE" ISSUES="$ISSUES" PLAN="$PLAN" python3 - <<'PY'
import copy, importlib.util, json, os, pathlib, time
platform=pathlib.Path(os.environ['PLATFORM'])
spec=importlib.util.spec_from_file_location('lifeos_backlog_runner',platform/'governor/backlog_runner.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
raw=json.loads(pathlib.Path(os.environ['ISSUES']).read_text())
issues=[x for x in raw if 'pull_request' not in x]
state=json.loads(pathlib.Path(os.environ['STATE']).read_text())
if state.get('active'):
    raise SystemExit('ERROR: backlog state already has active job')
now=int(time.time())
issue=mod.choose_issue(issues,state,now)
out={'eligible':False,'timestamp':now}
if issue is not None:
    captured={}
    working=copy.deepcopy(state)
    selected=copy.deepcopy(issue)
    def fake_api(path,method='GET',body=None):
        if path!='/jobs?async=1' or method!='POST': raise RuntimeError('unexpected canonical API call')
        captured['path']=path; captured['method']=method; captured['body']=copy.deepcopy(body)
        return {'id':'__LIFEOS_SINGLE_GATED_SENTINEL__'}
    mod.api=fake_api
    mod.issue_comment=lambda *a,**k: None
    mod.save_state=lambda *a,**k: None
    mod.now=lambda: now
    mod.submit_issue(selected,working)
    active=working.get('active') or {}
    out={
      'eligible':True,'timestamp':now,'issue':int(issue['number']),'title':str(issue.get('title') or ''),
      'path':captured['path'],'method':captured['method'],'request':captured['body']['request'],
      'dispatch_builder':captured['body']['dispatch_builder'],'phase':active.get('phase'),
      'target_id':active.get('target_id'),'prospective_state':working,
    }
pathlib.Path(os.environ['PLAN']).write_text(json.dumps(out,sort_keys=True)+'\n')
PY

ELIGIBLE=$(runuser -u joshan -- python3 -c 'import json,sys; print("yes" if json.load(open(sys.argv[1]))["eligible"] else "no")' "$PLAN")
if [[ "$ELIGIBLE" == no ]]; then
  echo 'ELIGIBLE_ISSUE=none'
  echo 'AUTHORITATIVE_SUBMISSION=NONE'
  echo 'LEGACY_RUNNER_CHANGED=NO'
  echo 'RESULT=PASS'
  echo 'NEXT_ACTION=rerun_when_an_eligible_issue_exists'
  exit 0
fi

ISSUE=$(runuser -u joshan -- python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["issue"])' "$PLAN")
PHASE=$(runuser -u joshan -- python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["phase"] or "none")' "$PLAN")
BUILDER=$(runuser -u joshan -- python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["dispatch_builder"])' "$PLAN")
TARGET=$(runuser -u joshan -- python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["target_id"] or "none")' "$PLAN")
echo "ELIGIBLE_ISSUE=$ISSUE"
echo "DISPATCH_PHASE=$PHASE"
echo "DISPATCH_BUILDER=$BUILDER"
echo "DISPATCH_TARGET=$TARGET"

if [[ "$MODE" == --check ]]; then
  echo 'AUTHORITATIVE_SUBMISSION=ARMED_NOT_EXECUTED'
  echo 'RESULT=PASS'
  echo 'NEXT_ACTION=rerun_with_--execute_for_exactly_one_submission'
  exit 0
fi

TIMER_WAS_ACTIVE=$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)
restore_timer() {
  if [[ "$TIMER_WAS_ACTIVE" == active ]]; then systemctl start lifeos-backlog-runner.timer >/dev/null 2>&1 || true; fi
}
trap 'restore_timer; rm -rf "$TMP"' EXIT
systemctl stop lifeos-backlog-runner.timer
[[ "$(systemctl is-active lifeos-backlog-runner.service 2>/dev/null || true)" != active ]] || { echo 'ERROR: legacy runner raced transaction'; exit 1; }

python3 - "$STATE" <<'PY'
import json,sys
if json.load(open(sys.argv[1])).get('active'): raise SystemExit('ERROR: backlog became active before submission')
PY
ACTIVE_GOV=$(python3 - "$GOV" <<'PY'
import json,sys,urllib.request
with urllib.request.urlopen(sys.argv[1]+'/jobs',timeout=10) as r: data=json.load(r)
if isinstance(data,dict): data=data.get('jobs',data.get('items',[]))
print(sum(str(j.get('status','')).upper() in {'QUEUED','RUNNING'} for j in data))
PY
)
[[ "$ACTIVE_GOV" == 0 ]] || { echo 'ERROR: governor became busy before submission'; exit 1; }

RESPONSE=$TMP/response.json
PLAN="$PLAN" TOKEN="$TOKEN" GOV="$GOV" RESPONSE="$RESPONSE" python3 - <<'PY'
import json,os,pathlib,urllib.request
p=json.loads(pathlib.Path(os.environ['PLAN']).read_text())
body=json.dumps({'request':p['request'],'dispatch_builder':p['dispatch_builder']}).encode()
req=urllib.request.Request(os.environ['GOV']+'/jobs?async=1',data=body,method='POST',headers={
 'Content-Type':'application/json','Authorization':'Bearer '+pathlib.Path(os.environ['TOKEN']).read_text().strip()})
with urllib.request.urlopen(req,timeout=45) as r: response=json.load(r)
pathlib.Path(os.environ['RESPONSE']).write_text(json.dumps(response,sort_keys=True)+'\n')
PY
JOB_ID=$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1])).get("id") or ""))' "$RESPONSE")
[[ -n "$JOB_ID" ]] || { echo 'ERROR: Governor returned no job id'; exit 1; }
echo "GOVERNOR_JOB_ID=$JOB_ID"

PLAN="$PLAN" STATE="$STATE" JOB_ID="$JOB_ID" runuser -u joshan -- env PLAN="$PLAN" STATE="$STATE" JOB_ID="$JOB_ID" python3 - <<'PY'
import json,os,pathlib
plan=json.loads(pathlib.Path(os.environ['PLAN']).read_text())
state=plan['prospective_state']
active=state.get('active') or {}
if active.get('job_id')!='__LIFEOS_SINGLE_GATED_SENTINEL__': raise SystemExit('prospective canonical state sentinel missing')
active['job_id']=os.environ['JOB_ID']
p=pathlib.Path(os.environ['STATE']); tmp=p.with_suffix('.semaphore-once.tmp')
tmp.write_text(json.dumps(state,indent=2,sort_keys=True)+'\n'); tmp.replace(p)
PY

ROUTE=normal
[[ "$BUILDER" == local ]] && ROUTE=local-only
runuser -u joshan -- gh issue comment "$ISSUE" --repo "$REPO_FULL" --body "### LifeOS autonomous backlog start
- Selected after a complete open-issue refresh and priority/dependency eligibility pass.
- LifeOS job: \`$JOB_ID\`
- Route: \`$ROUTE\`
- State: \`IN_PROGRESS\`
- Dispatcher: \`Semaphore one-shot gated submission\`" >/dev/null

restore_timer
trap 'rm -rf "$TMP"' EXIT
[[ "$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)" == active || "$TIMER_WAS_ACTIVE" != active ]] || { echo 'ERROR: legacy timer not restored'; exit 1; }
python3 - "$STATE" "$JOB_ID" <<'PY'
import json,sys
active=json.load(open(sys.argv[1])).get('active') or {}
if str(active.get('job_id'))!=sys.argv[2]: raise SystemExit('ERROR: canonical backlog state does not contain submitted job')
PY
python3 - "$GOV" "$JOB_ID" <<'PY'
import json,sys,urllib.request
with urllib.request.urlopen(sys.argv[1]+'/jobs/'+sys.argv[2],timeout=10) as r: j=json.load(r)
if str(j.get('id') or '')!=sys.argv[2]: raise SystemExit('ERROR: Governor job lookup mismatch')
print('GOVERNOR_ACCEPTANCE=PASS')
print('GOVERNOR_STATUS='+str(j.get('status') or 'unknown'))
PY
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository changed'; exit 1; }
[[ "$(stat -c '%U:%G' "$PLATFORM/.git/index")" == 'joshan:joshan' ]] || { echo 'ERROR: git metadata ownership changed'; exit 1; }

echo
echo 'RESULT=PASS'
echo 'SEMAPHORE_SINGLE_GATED_SUBMISSION=PASS'
echo 'AUTHORITATIVE_SUBMISSIONS=1'
echo 'GOVERNOR_CREDENTIAL_IN_SEMAPHORE=NO'
echo 'LEGACY_TIMER_RESTORED=YES'
echo 'CANONICAL_BACKLOG_STATE_UPDATED=YES'
echo 'PLATFORM_MUTATION=NONE'
echo 'NEXT_ACTION=observe_this_single_job_to_terminal_then_compare_legacy_completion_handling'
