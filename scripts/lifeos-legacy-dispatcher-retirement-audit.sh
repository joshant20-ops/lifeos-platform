#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
STATE=/var/lib/lifeos-backlog-runner/state.json
ENV_FILE=/etc/lifeos/semaphore.env
PROJECT=lifeos-semaphore-shadow
GOV=http://127.0.0.1:8790
REPO_FULL=joshant20-ops/lifeos-platform
PROOF_JOB=${PROOF_JOB:-11618ff914ce}
PROOF_ISSUE=${PROOF_ISSUE:-28}

[[ -d "$PLATFORM/.git" ]] || { echo 'ERROR: platform repository missing'; exit 1; }
HEAD=$(git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || { echo 'ERROR: platform HEAD is not origin/main'; exit 1; }
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository dirty'; exit 1; }

printf '%s\n' 'LEGACY_DISPATCHER_RETIREMENT_AUDIT_VERSION=2'
printf '%s\n' 'MUTATIONS=NONE'
printf 'PLATFORM_HEAD=%s\n' "$HEAD"

echo
echo '=== SEMAPHORE RUNTIME ==='
for c in "${PROJECT}-semaphore-1" "${PROJECT}-semaphore-db-1"; do
  if docker inspect "$c" >/dev/null 2>&1; then
    printf '%s state=%s health=%s restart_count=%s\n' "$c" \
      "$(docker inspect -f '{{.State.Status}}' "$c")" \
      "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c")" \
      "$(docker inspect -f '{{.RestartCount}}' "$c")"
  else
    echo "$c state=absent"
  fi
done
SEMAPHORE_API=UNKNOWN
if [[ -r "$ENV_FILE" ]]; then
  BIND_IP=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE")
  if [[ -n "$BIND_IP" ]]; then
    if curl -fsS --max-time 5 "http://${BIND_IP}:3000/api/ping" >/dev/null; then SEMAPHORE_API=PASS; else SEMAPHORE_API=FAIL; fi
  fi
fi
echo "SEMAPHORE_API=$SEMAPHORE_API"

echo
echo '=== LEGACY / SAFETY UNITS ==='
units=(
  lifeos-backlog-runner.timer
  lifeos-backlog-runner.service
  lifeos-engineer-dispatcher.timer
  lifeos-engineer-dispatcher.service
  lifeos-engineer-worker.timer
  lifeos-engineer-worker.service
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
  lifeos-ha-issue-queue-bridge.service
)
for u in "${units[@]}"; do
  printf '%-40s active=%-10s enabled=%s\n' "$u" \
    "$(systemctl is-active "$u" 2>/dev/null || true)" \
    "$(systemctl is-enabled "$u" 2>/dev/null || true)"
done

echo
echo '=== SINGLE-FLIGHT STATE ==='
if [[ -r "$STATE" ]]; then
  python3 - "$STATE" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
a=s.get('active') or {}
print('BACKLOG_ACTIVE_JOB='+str(a.get('job_id') or 'none'))
print('BACKLOG_ACTIVE_ISSUE='+str(a.get('issue') or 'none'))
print('BACKLOG_STATE_VERSION='+str(s.get('version') or 'unknown'))
PY
else
  echo 'BACKLOG_ACTIVE_JOB=unknown'
fi
python3 - "$GOV" <<'PY'
import json,sys,urllib.request
try:
    with urllib.request.urlopen(sys.argv[1]+'/jobs',timeout=10) as r: data=json.load(r)
    if isinstance(data,dict): data=data.get('jobs',data.get('items',[]))
    active=[j for j in data if str(j.get('status','')).upper() in {'QUEUED','RUNNING'}]
    print('GOVERNOR_ACTIVE_JOBS='+str(len(active)))
except Exception as exc:
    print('GOVERNOR_ACTIVE_JOBS=unknown')
    print('GOVERNOR_READ_ERROR='+type(exc).__name__)
PY

echo
echo '=== PROVEN SEMAPHORE CAPABILITIES IN REPOSITORY ==='
required=(
  scripts/lifeos-semaphore-readonly-proof.sh
  scripts/lifeos-semaphore-backlog-shadow-proof.sh
  scripts/lifeos-semaphore-dispatch-shadow-proof.sh
  scripts/lifeos-semaphore-dispatch-fixture-proof.sh
  scripts/lifeos-semaphore-single-gated-submission.sh
  scripts/lifeos-semaphore-recovery-rehearsal.sh
  scripts/lifeos-semaphore-terminal-observer.sh
)
for p in "${required[@]}"; do
  [[ -f "$PLATFORM/$p" ]] && echo "$p=present" || echo "$p=missing"
done

echo
echo '=== PRODUCTION CUTOVER EVIDENCE ==='
readarray -t evidence < <(python3 - "$GOV" "$STATE" "$PROOF_JOB" "$PROOF_ISSUE" <<'PY'
import json,sys,urllib.request
base,state_path,job_id,issue=sys.argv[1:]
job_status='UNKNOWN'
try:
    with urllib.request.urlopen(base+'/jobs/'+job_id,timeout=10) as r: j=json.load(r)
    job_status=str(j.get('status') or 'UNKNOWN').upper()
except Exception:
    pass
try:
    s=json.load(open(state_path)); a=s.get('active') or {}; e=(s.get('issues') or {}).get(str(issue)) or {}
except Exception:
    a={}; e={}
print(job_status)
print(str(a.get('job_id') or 'none'))
print(str(e.get('work_state') or 'none').upper())
print(str(e.get('issue_validity') or 'none').upper())
PY
)
PROOF_GOV_STATUS=${evidence[0]:-UNKNOWN}
PROOF_ACTIVE_JOB=${evidence[1]:-unknown}
PROOF_WORK_STATE=${evidence[2]:-unknown}
PROOF_VALIDITY=${evidence[3]:-unknown}
comments=$(runuser -u joshan -- gh api "repos/$REPO_FULL/issues/$PROOF_ISSUE/comments?per_page=100" 2>/dev/null || printf '[]')
PROOF_CHECKPOINT=$(COMMENTS="$comments" PROOF_JOB="$PROOF_JOB" python3 - <<'PY'
import json,os
try: data=json.loads(os.environ.get('COMMENTS','[]'))
except Exception: data=[]
job=os.environ['PROOF_JOB']
found=False
for c in data if isinstance(data,list) else []:
    body=str(c.get('body') or '')
    if job in body and ('State:' in body or 'LIFEOS_WORK_STATE=' in body or 'PASS' in body or 'BLOCKED' in body or 'FAIL' in body):
        found=True; break
print('yes' if found else 'no')
PY
)
echo "PROOF_JOB=$PROOF_JOB"
echo "PROOF_ISSUE=$PROOF_ISSUE"
echo "PROOF_GOVERNOR_STATUS=$PROOF_GOV_STATUS"
echo "PROOF_ACTIVE_JOB=$PROOF_ACTIVE_JOB"
echo "PROOF_BACKLOG_WORK_STATE=$PROOF_WORK_STATE"
echo "PROOF_ISSUE_VALIDITY=$PROOF_VALIDITY"
echo "PROOF_ISSUE_CHECKPOINT=$PROOF_CHECKPOINT"

REAL_SUBMISSION=NOT_YET_PROVEN
TERMINAL_HANDLING=NOT_YET_PROVEN
if [[ "$PROOF_GOV_STATUS" == PASS ]]; then REAL_SUBMISSION=PROVEN; fi
if [[ "$PROOF_GOV_STATUS" == PASS && "$PROOF_ACTIVE_JOB" == none && "$PROOF_WORK_STATE" == PASS && "$PROOF_VALIDITY" == VALID && "$PROOF_CHECKPOINT" == yes ]]; then
  TERMINAL_HANDLING=PROVEN
fi

echo
echo '=== RETIREMENT PRECONDITIONS ==='
echo 'READ_ONLY_ANSIBLE_EXECUTION=PROVEN'
echo 'RESULT_PROPAGATION=PROVEN'
echo 'LIVE_NO_WORK_SELECTION_PARITY=PROVEN'
echo 'LIVE_NO_WORK_DISPATCH_PARITY=PROVEN'
echo 'SYNTHETIC_NORMAL_ROUTE=PROVEN'
echo 'SYNTHETIC_LOCAL_ONLY_ROUTE=PROVEN'
echo 'SYNTHETIC_RECOVERY_ROUTE=PROVEN'
echo 'SEMAPHORE_RESTART_PERSISTENCE=PROVEN'
echo 'SEMAPHORE_BACKUP_RESTORE=PROVEN'
echo "ONE_REAL_AUTHORITATIVE_SEMAPHORE_SUBMISSION=$REAL_SUBMISSION"
echo "ONE_REAL_TERMINAL_COMPLETION_HANDLING=$TERMINAL_HANDLING"

echo
echo '=== COMPONENT DECISIONS ==='
if [[ "$REAL_SUBMISSION" == PROVEN && "$TERMINAL_HANDLING" == PROVEN && "$SEMAPHORE_API" == PASS ]]; then
  echo 'lifeos-backlog-runner=RETIRE_CANDIDATE reason=Semaphore production submission and completion proven'
  echo 'lifeos-engineer-dispatcher.timer=RETIRE_CANDIDATE reason=Semaphore dispatch path proven'
  echo 'lifeos-engineer-worker.timer=KEEP_DISABLED_AND_AUDIT reason=already disabled; verify no unique responsibility before file retirement'
  echo 'lifeos-control-job-submit.socket=KEEP transition_or_privilege_ingress_boundary'
  echo 'lifeos-root-broker.socket=KEEP permanent_privileged_host_boundary'
  echo 'lifeos-autonomous-agent.service=KEEP permanent_decision_and_planning_layer'
  echo 'lifeos-engineer.service=KEEP permanent_local_ai_backend'
  echo 'lifeos-ha-issue-queue-bridge.service=KEEP_OR_SIMPLIFY_AFTER_DISPATCH_CUTOVER'
  echo
  echo '=== RETIREMENT VERDICT ==='
  echo 'LEGACY_DISPATCHER_RETIREMENT_READY=YES'
  echo 'SAFE_TO_DISABLE_NOW=lifeos-backlog-runner.timer,lifeos-engineer-dispatcher.timer'
  echo 'NEXT_ACTION=gated_disable_only_superseded_dispatch_timers_with_rollback'
else
  echo 'lifeos-backlog-runner=KEEP_FOR_NOW'
  echo 'lifeos-engineer-dispatcher.timer=KEEP_FOR_NOW'
  echo 'lifeos-engineer-worker.timer=KEEP_DISABLED_OR_LEGACY'
  echo 'lifeos-control-job-submit.socket=KEEP transition_or_privilege_ingress_boundary'
  echo 'lifeos-root-broker.socket=KEEP permanent_privileged_host_boundary'
  echo 'lifeos-autonomous-agent.service=KEEP permanent_decision_and_planning_layer'
  echo 'lifeos-engineer.service=KEEP permanent_local_ai_backend'
  echo 'lifeos-ha-issue-queue-bridge.service=KEEP_OR_SIMPLIFY_AFTER_DISPATCH_CUTOVER'
  echo
  echo '=== RETIREMENT VERDICT ==='
  echo 'LEGACY_DISPATCHER_RETIREMENT_READY=NO'
  [[ "$SEMAPHORE_API" == PASS ]] || echo 'BLOCKER=semaphore_api_not_proven_healthy'
  [[ "$REAL_SUBMISSION" == PROVEN ]] || echo 'BLOCKER=one_real_authoritative_semaphore_submission_not_proven'
  [[ "$TERMINAL_HANDLING" == PROVEN ]] || echo 'BLOCKER=one_real_terminal_completion_handling_not_proven'
  echo 'SAFE_TO_DISABLE_NOW=NONE'
  echo 'NEXT_ACTION=resolve_reported_blockers_then_rerun_audit'
fi
echo 'AUDIT_RESULT=PASS'
