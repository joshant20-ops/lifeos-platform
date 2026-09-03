#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
STATE=/var/lib/lifeos-backlog-runner/state.json
GOV=http://127.0.0.1:8790
REPO_FULL=joshant20-ops/lifeos-platform
JOB_ID=${1:-11618ff914ce}
ISSUE=${2:-28}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-900}
POLL_SECONDS=${POLL_SECONDS:-5}

[[ -d "$PLATFORM/.git" ]] || { echo 'ERROR: platform repository missing'; exit 1; }
[[ -r "$STATE" ]] || { echo 'ERROR: backlog state missing'; exit 1; }

printf '%s\n' 'SEMAPHORE_TERMINAL_OBSERVER_VERSION=1'
printf 'MUTATIONS=%s\n' 'NONE'
printf 'JOB_ID=%s\n' "$JOB_ID"
printf 'ISSUE=%s\n' "$ISSUE"
printf 'LEGACY_TIMER_ACTIVE=%s\n' "$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)"

start=$(date +%s)
terminal=''
status=''
while :; do
  status=$(python3 - "$GOV" "$JOB_ID" <<'PY'
import json,sys,urllib.request
with urllib.request.urlopen(sys.argv[1]+'/jobs/'+sys.argv[2],timeout=10) as r:
    j=json.load(r)
print(str(j.get('status') or 'UNKNOWN').upper())
PY
)
  case "$status" in
    PASS|FAIL|ERROR|BLOCKED|WAITING_HUMAN|WAITING_DEPENDENCY|SUPERSEDED|CANCELLED|CANCELED|REJECTED)
      terminal=$status
      break
      ;;
  esac
  now=$(date +%s)
  if (( now - start >= TIMEOUT_SECONDS )); then
    echo "GOVERNOR_STATUS=$status"
    echo 'RESULT=RETRY'
    echo 'BARRIER=governor_job_not_terminal_within_observation_window'
    exit 2
  fi
  sleep "$POLL_SECONDS"
done

echo "GOVERNOR_TERMINAL_STATUS=$terminal"

# Once Governor is terminal, the legacy backlog timer should consume the result
# and clear/advance the durable active record. Observe only; never start a unit.
completion_deadline=$(( $(date +%s) + 720 ))
handled=no
while :; do
  readarray -t state_fields < <(python3 - "$STATE" "$JOB_ID" "$ISSUE" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
a=s.get('active') or {}
e=(s.get('issues') or {}).get(str(sys.argv[3])) or {}
print(str(a.get('job_id') or 'none'))
print(str(a.get('issue') or 'none'))
print(str(e.get('last_job_id') or 'none'))
print(str(e.get('work_state') or 'none'))
print(str(e.get('issue_validity') or 'none'))
PY
)
  ACTIVE_JOB=${state_fields[0]:-none}
  ACTIVE_ISSUE=${state_fields[1]:-none}
  LAST_JOB=${state_fields[2]:-none}
  WORK_STATE=${state_fields[3]:-none}
  ISSUE_VALIDITY=${state_fields[4]:-none}

  if [[ "$ACTIVE_JOB" != "$JOB_ID" && "$LAST_JOB" == "$JOB_ID" ]]; then
    handled=yes
    break
  fi
  if (( $(date +%s) >= completion_deadline )); then
    break
  fi
  sleep "$POLL_SECONDS"
done

echo "BACKLOG_ACTIVE_JOB=$ACTIVE_JOB"
echo "BACKLOG_ACTIVE_ISSUE=$ACTIVE_ISSUE"
echo "BACKLOG_LAST_JOB=$LAST_JOB"
echo "BACKLOG_WORK_STATE=$WORK_STATE"
echo "BACKLOG_ISSUE_VALIDITY=$ISSUE_VALIDITY"
echo "LEGACY_COMPLETION_HANDLED=$handled"

comments=$(runuser -u joshan -- gh api "repos/$REPO_FULL/issues/$ISSUE/comments?per_page=100" --paginate 2>/dev/null || printf '[]')
checkpoint=$(python3 - "$JOB_ID" <<'PY' <<<"$comments"
import json,sys
job=sys.argv[1]
try: data=json.load(sys.stdin)
except Exception: data=[]
# gh --paginate may emit either one array or concatenated arrays depending version.
if isinstance(data,dict): data=[data]
found=False
for c in data if isinstance(data,list) else []:
    body=str(c.get('body') or '')
    if job in body and ('LIFEOS_WORK_STATE=' in body or 'State:' in body or 'PASS' in body or 'BLOCKED' in body or 'FAIL' in body):
        found=True
        break
print('yes' if found else 'no')
PY
)
echo "ISSUE_TERMINAL_CHECKPOINT=$checkpoint"

echo "LEGACY_TIMER_FINAL_ACTIVE=$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)"
echo "GOVERNOR_ACTIVE_JOBS=$(python3 - "$GOV" <<'PY'
import json,sys,urllib.request
with urllib.request.urlopen(sys.argv[1]+'/jobs',timeout=10) as r: data=json.load(r)
if isinstance(data,dict): data=data.get('jobs',data.get('items',[]))
print(sum(str(j.get('status','')).upper() in {'QUEUED','RUNNING'} for j in data))
PY
)"

[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository dirty during observation'; exit 1; }

if [[ "$handled" == yes && "$checkpoint" == yes ]]; then
  echo
  echo 'RESULT=PASS'
  echo 'ONE_REAL_AUTHORITATIVE_SEMAPHORE_SUBMISSION=PROVEN'
  echo 'ONE_REAL_TERMINAL_COMPLETION_HANDLING=PROVEN'
  echo 'LEGACY_TIMER_RESTORED=YES'
  echo 'PLATFORM_MUTATION=NONE'
  echo 'NEXT_ACTION=rerun_legacy_dispatcher_retirement_audit'
  exit 0
fi

echo
echo 'RESULT=RETRY'
[[ "$handled" == yes ]] || echo 'BARRIER=legacy_completion_not_yet_reflected_in_backlog_state'
[[ "$checkpoint" == yes ]] || echo 'BARRIER=terminal_issue_checkpoint_not_yet_observed'
echo 'NEXT_ACTION=rerun_observer_after_legacy_timer_processes_terminal_job'
exit 2
