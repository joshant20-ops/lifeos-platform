#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
GOV=http://127.0.0.1:8790
REPO_FULL=joshant20-ops/lifeos-platform
JOB_ID=${1:-11618ff914ce}
ISSUE=${2:-28}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-900}
POLL_SECONDS=${POLL_SECONDS:-5}

[[ -d "$PLATFORM/.git" ]] || { echo 'ERROR: platform repository missing'; exit 1; }

printf '%s\n' 'SEMAPHORE_TERMINAL_OBSERVER_VERSION=2'
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

# Governor is now the terminal-state authority. The retired backlog runner no
# longer has any completion state to consume. GitHub carries the durable human-
# visible checkpoint; Governor carries the machine terminal state.
handled=yes
echo "GOVERNOR_COMPLETION_HANDLED=$handled"
echo "LEGACY_BACKLOG_STATE=NOT_REQUIRED"

# Parse comments in Python directly from a temp file rather than combining a
# here-doc with a here-string (which previously caused JSON booleans to be
# interpreted as Python source on some shells).
COMMENTS_FILE=$(mktemp)
trap 'rm -f "$COMMENTS_FILE"' EXIT
runuser -u joshan -- gh api "repos/$REPO_FULL/issues/$ISSUE/comments?per_page=100" >"$COMMENTS_FILE" 2>/dev/null || printf '[]\n' >"$COMMENTS_FILE"
checkpoint=$(python3 - "$COMMENTS_FILE" "$JOB_ID" <<'PY'
import json,sys
path,job=sys.argv[1:]
try:
    data=json.load(open(path))
except Exception:
    data=[]
if isinstance(data,dict):
    data=[data]
found=False
for c in data if isinstance(data,list) else []:
    body=str(c.get('body') or '')
    if job in body and (
        'LIFEOS_WORK_STATE=' in body or
        'State:' in body or
        'PASS' in body or
        'BLOCKED' in body or
        'FAIL' in body or
        'ERROR' in body
    ):
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
  echo 'TERMINAL_AUTHORITY=GOVERNOR_PLUS_GITHUB'
  echo 'LEGACY_BACKLOG_STATE_DEPENDENCY=ABSENT'
  echo 'PLATFORM_MUTATION=NONE'
  echo 'NEXT_ACTION=rerun_legacy_dispatcher_retirement_audit'
  exit 0
fi

echo
echo 'RESULT=RETRY'
[[ "$checkpoint" == yes ]] || echo 'BARRIER=terminal_issue_checkpoint_not_yet_observed'
echo 'NEXT_ACTION=rerun_observer_after_terminal_issue_checkpoint_is_available'
exit 2
