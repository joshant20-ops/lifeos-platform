#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
WORKER=/home/joshan/automation/queues/lifeos_engineer_worker.py
DISPATCHER=/home/joshan/automation/queues/lifeos_engineer_dispatcher.py
UNITS=(
  /etc/systemd/system/lifeos-engineer-worker.service
  /etc/systemd/system/lifeos-engineer-worker.timer
  /etc/systemd/system/lifeos-engineer-dispatcher.service
  /etc/systemd/system/lifeos-engineer-dispatcher.timer
)

[[ -d "$PLATFORM/.git" ]] || { echo 'ERROR: platform repository missing'; exit 1; }
HEAD=$(git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || { echo 'ERROR: platform HEAD is not origin/main'; exit 1; }
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository dirty'; exit 1; }

printf '%s\n' 'DISABLED_ENGINEER_WORKER_AUDIT_VERSION=1'
printf '%s\n' 'MUTATIONS=NONE'
printf 'PLATFORM_HEAD=%s\n' "$HEAD"

echo
echo '=== UNIT STATE ==='
for u in lifeos-engineer-worker.timer lifeos-engineer-worker.service lifeos-engineer-dispatcher.timer lifeos-engineer-dispatcher.service; do
  printf '%-40s active=%-10s enabled=%s\n' "$u" \
    "$(systemctl is-active "$u" 2>/dev/null || true)" \
    "$(systemctl is-enabled "$u" 2>/dev/null || true)"
done

echo
echo '=== LIVE FILE METADATA ==='
for f in "$WORKER" "$DISPATCHER" "${UNITS[@]}"; do
  if [[ -e "$f" ]]; then
    stat -c 'present=yes owner=%U group=%G mode=%a bytes=%s path=%n' "$f"
  else
    echo "present=no path=$f"
  fi
done

echo
echo '=== WORKER RESPONSIBILITY SIGNALS ==='
if [[ -r "$WORKER" ]]; then
  grep -nEi 'queue|retry|attempt|lock|state|result|github|gh |api|token|socket|root|sudo|systemctl|subprocess|requests|urllib|mqtt|job|dispatch|archive|pending|staging|semaphore|ansible' "$WORKER" || true
else
  echo 'worker_file_unreadable_or_absent'
fi

echo
echo '=== DISPATCHER RESPONSIBILITY SIGNALS ==='
if [[ -r "$DISPATCHER" ]]; then
  grep -nEi 'queue|retry|attempt|lock|state|result|github|gh |api|token|socket|root|sudo|systemctl|subprocess|requests|urllib|mqtt|job|dispatch|archive|pending|staging|semaphore|ansible' "$DISPATCHER" || true
else
  echo 'dispatcher_file_unreadable_or_absent'
fi

echo
echo '=== PLATFORM REFERENCES ==='
grep -RIn --exclude-dir=.git -E 'lifeos-engineer-worker|lifeos_engineer_worker|lifeos-engineer-dispatcher|lifeos_engineer_dispatcher|/home/joshan/automation/queues' "$PLATFORM" 2>/dev/null || true

echo
echo '=== SYSTEMD DEFINITIONS ==='
for f in "${UNITS[@]}"; do
  if [[ -r "$f" ]]; then
    echo "--- $f ---"
    cat "$f"
  fi
done

echo
echo '=== CURRENT REPLACEMENT BOUNDARIES ==='
for u in lifeos-control-job-submit.socket lifeos-root-broker.socket lifeos-autonomous-agent.service lifeos-engineer.service lifeos-ha-issue-queue-bridge.service; do
  printf '%-40s active=%-10s enabled=%s\n' "$u" \
    "$(systemctl is-active "$u" 2>/dev/null || true)" \
    "$(systemctl is-enabled "$u" 2>/dev/null || true)"
done

# Conservative classification: this audit only identifies evidence. It does not
# delete or disable any additional component.
worker_present=no; dispatcher_present=no
[[ -f "$WORKER" ]] && worker_present=yes
[[ -f "$DISPATCHER" ]] && dispatcher_present=yes
worker_timer=$(systemctl is-active lifeos-engineer-worker.timer 2>/dev/null || true)
dispatch_timer=$(systemctl is-active lifeos-engineer-dispatcher.timer 2>/dev/null || true)

echo
echo '=== CLASSIFICATION ==='
echo "WORKER_FILE_PRESENT=$worker_present"
echo "DISPATCHER_FILE_PRESENT=$dispatcher_present"
echo "WORKER_TIMER_ACTIVE=${worker_timer:-unknown}"
echo "DISPATCHER_TIMER_ACTIVE=${dispatch_timer:-unknown}"
echo 'UNIQUE_RESPONSIBILITY=REQUIRES_REVIEW_OF_EVIDENCE_ABOVE'
echo 'SAFE_TO_DELETE_NOW=NO'
echo 'NEXT_ACTION=classify_worker_dispatcher_responsibilities_then_create_gated_file_retirement_only_if_no_unique_function_remains'
echo 'AUDIT_RESULT=PASS'
