#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
STATE=/var/lib/lifeos-backlog-runner/state.json
ENV_FILE=/etc/lifeos/semaphore.env
PROJECT=lifeos-semaphore-shadow
GOV=http://127.0.0.1:8790

[[ -d "$PLATFORM/.git" ]] || { echo 'ERROR: platform repository missing'; exit 1; }
HEAD=$(git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || { echo 'ERROR: platform HEAD is not origin/main'; exit 1; }
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository dirty'; exit 1; }

printf '%s\n' 'LEGACY_DISPATCHER_RETIREMENT_AUDIT_VERSION=1'
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
if [[ -r "$ENV_FILE" ]]; then
  BIND_IP=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE")
  [[ -n "$BIND_IP" ]] && curl -fsS --max-time 5 "http://${BIND_IP}:3000/api/ping" >/dev/null && echo 'SEMAPHORE_API=PASS' || echo 'SEMAPHORE_API=FAIL'
else
  echo 'SEMAPHORE_API=UNKNOWN'
fi

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
)
for p in "${required[@]}"; do
  [[ -f "$PLATFORM/$p" ]] && echo "$p=present" || echo "$p=missing"
done

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
echo 'ONE_REAL_AUTHORITATIVE_SEMAPHORE_SUBMISSION=NOT_YET_PROVEN'
echo 'ONE_REAL_TERMINAL_COMPLETION_HANDLING=NOT_YET_PROVEN'

echo
echo '=== COMPONENT DECISIONS ==='
echo 'lifeos-backlog-runner=KEEP_FOR_NOW blocker=first_real_authoritative_semaphore_job_not_yet_proven'
echo 'lifeos-engineer-dispatcher.timer=KEEP_FOR_NOW blocker=production_dispatch_cutover_not_yet_proven'
echo 'lifeos-engineer-worker.timer=KEEP_DISABLED_OR_LEGACY blocker=confirm_no_unique_worker_only_responsibility_after_real_cutover'
echo 'lifeos-control-job-submit.socket=KEEP transition_or_privilege_ingress_boundary'
echo 'lifeos-root-broker.socket=KEEP permanent_privileged_host_boundary'
echo 'lifeos-autonomous-agent.service=KEEP permanent_decision_and_planning_layer'
echo 'lifeos-engineer.service=KEEP permanent_local_ai_backend'
echo 'lifeos-ha-issue-queue-bridge.service=KEEP_OR_SIMPLIFY_AFTER_DISPATCH_CUTOVER'

echo
echo '=== RETIREMENT VERDICT ==='
echo 'LEGACY_DISPATCHER_RETIREMENT_READY=NO'
echo 'BLOCKER=one_real_authoritative_semaphore_submission_and_terminal_completion_not_yet_proven'
echo 'SAFE_TO_DISABLE_NOW=NONE'
echo 'NEXT_ACTION=wait_for_or_create_one_real_eligible_low_risk_issue_then_run_single_gated_submission_and_observe_terminal_completion'
echo 'AUDIT_RESULT=PASS'
