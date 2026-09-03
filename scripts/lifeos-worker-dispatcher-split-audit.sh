#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
PROJECT=lifeos-semaphore-shadow
QUEUE=/home/joshan/automation/queues/engineer_job_queue.jsonl

failures=()
record_failure(){ failures+=("$1"); }

printf '%s\n' 'LIFEOS_POST_RETIREMENT_HEALTH_AUDIT_VERSION=1'
printf '%s\n' 'MUTATIONS=NONE'
printf 'PLATFORM_HEAD=%s\n' "$(git -C "$PLATFORM" rev-parse HEAD)"

echo
echo '=== REPOSITORY ==='
HEAD=$(git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(git -C "$PLATFORM" rev-parse origin/main)
STATUS=$(git -C "$PLATFORM" status --porcelain)
printf 'HEAD=%s\nORIGIN_MAIN=%s\n' "$HEAD" "$ORIGIN"
if [[ "$HEAD" == "$ORIGIN" ]]; then echo 'REPO_HEAD_MATCH=PASS'; else echo 'REPO_HEAD_MATCH=FAIL'; record_failure repo_head_mismatch; fi
if [[ -z "$STATUS" ]]; then echo 'REPO_CLEAN=PASS'; else echo 'REPO_CLEAN=FAIL'; record_failure repo_dirty; fi

echo
echo '=== RETIRED DISPATCHER ARTIFACTS ==='
retired_paths=(
  /home/joshan/automation/queues/lifeos_engineer_worker.py
  /home/joshan/automation/queues/lifeos_engineer_dispatcher.py
  /home/joshan/automation/queues/lifeos_engineer_maintenance.py
  /etc/systemd/system/lifeos-engineer-worker.service
  /etc/systemd/system/lifeos-engineer-worker.timer
  /etc/systemd/system/lifeos-engineer-dispatcher.service
  /etc/systemd/system/lifeos-engineer-dispatcher.timer
)
retired_present=0
for p in "${retired_paths[@]}"; do
  if [[ -e "$p" || -L "$p" ]]; then
    echo "RETIRED_PATH_PRESENT=$p"
    retired_present=$((retired_present+1))
  fi
done
printf 'RETIRED_PATHS_PRESENT=%s\n' "$retired_present"
if (( retired_present == 0 )); then echo 'RETIRED_ARTIFACTS_ABSENT=PASS'; else echo 'RETIRED_ARTIFACTS_ABSENT=FAIL'; record_failure retired_artifacts_present; fi

for u in lifeos-engineer-worker.timer lifeos-engineer-dispatcher.timer; do
  active=$(systemctl is-active "$u" 2>/dev/null || true)
  enabled=$(systemctl is-enabled "$u" 2>/dev/null || true)
  printf '%s active=%s enabled=%s\n' "$u" "${active:-not-found}" "${enabled:-not-found}"
  if [[ "$active" == active || "$enabled" == enabled ]]; then record_failure "retired_unit_live_${u}"; fi
done

echo
echo '=== SEMAPHORE ==='
semaphore=${PROJECT}-semaphore-1
db=${PROJECT}-semaphore-db-1
for c in "$semaphore" "$db"; do
  if docker inspect "$c" >/dev/null 2>&1; then
    printf 'container=%s state=%s health=%s restart_count=%s\n' "$c" \
      "$(docker inspect -f '{{.State.Status}}' "$c")" \
      "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c")" \
      "$(docker inspect -f '{{.RestartCount}}' "$c")"
  else
    echo "container=$c state=absent"
    record_failure "container_absent_${c}"
  fi
done

SEMAPHORE_API=FAIL
bind=$(docker port "$semaphore" 3000/tcp 2>/dev/null | head -1 || true)
if [[ -n "$bind" ]]; then
  host=${bind%:*}; port=${bind##*:}; host=${host#[}; host=${host%]}
  if curl -fsS --max-time 5 "http://${host}:${port}/api/ping" >/dev/null; then SEMAPHORE_API=PASS; fi
fi
echo "SEMAPHORE_PUBLISHED_BIND=${bind:-none}"
echo "SEMAPHORE_API=$SEMAPHORE_API"
[[ "$SEMAPHORE_API" == PASS ]] || record_failure semaphore_api

echo
echo '=== PROTECTED LIFEOS BOUNDARIES ==='
protected=(
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
  lifeos-ha-issue-queue-bridge.service
)
for u in "${protected[@]}"; do
  active=$(systemctl is-active "$u" 2>/dev/null || true)
  enabled=$(systemctl is-enabled "$u" 2>/dev/null || true)
  printf '%s active=%s enabled=%s\n' "$u" "$active" "$enabled"
  [[ "$active" == active ]] || record_failure "protected_inactive_${u}"
done

echo
echo '=== QUEUE ==='
readarray -t q < <(python3 - "$QUEUE" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]); total=pending=invalid=0
if p.exists():
    for line in p.read_text(errors='replace').splitlines():
        if not line.strip(): continue
        total += 1
        try: d=json.loads(line)
        except Exception: invalid += 1; continue
        if str(d.get('status') or '').lower() == 'pending': pending += 1
print(f'QUEUE_PRESENT={"yes" if p.exists() else "no"}')
print(f'QUEUE_TOTAL={total}')
print(f'QUEUE_PENDING={pending}')
print(f'QUEUE_INVALID={invalid}')
print(pending)
print(invalid)
PY
)
printf '%s\n' "${q[0]:-QUEUE_PRESENT=no}" "${q[1]:-QUEUE_TOTAL=0}" "${q[2]:-QUEUE_PENDING=0}" "${q[3]:-QUEUE_INVALID=0}"
[[ ${q[4]:-0} -eq 0 ]] || record_failure queue_pending
[[ ${q[5]:-0} -eq 0 ]] || record_failure queue_invalid

echo
echo '=== GITHUB RUNNER ==='
runner_unit=$(systemctl list-unit-files 'actions.runner.joshant20-ops-lifeos-platform.lifeos-pi5.service' --no-legend 2>/dev/null | awk 'NR==1{print $1}')
if [[ -n "$runner_unit" ]]; then
  runner_active=$(systemctl is-active "$runner_unit" 2>/dev/null || true)
  runner_enabled=$(systemctl is-enabled "$runner_unit" 2>/dev/null || true)
  echo "GITHUB_RUNNER_UNIT=$runner_unit"
  echo "GITHUB_RUNNER_ACTIVE=$runner_active"
  echo "GITHUB_RUNNER_ENABLED=$runner_enabled"
  [[ "$runner_active" == active ]] || record_failure github_runner_inactive
else
  echo 'GITHUB_RUNNER_UNIT=none'
  record_failure github_runner_missing
fi

echo
echo '=== RESULT ==='
if (( ${#failures[@]} == 0 )); then
  echo 'POST_RETIREMENT_HEALTH=PASS'
  echo 'AUDIT_RESULT=PASS'
  echo 'NEXT_ACTION=continue_automatic_github_managed_operations'
  exit 0
fi
printf 'FAILURE_COUNT=%s\n' "${#failures[@]}"
printf 'FAILURES=%s\n' "$(IFS=,; echo "${failures[*]}")"
echo 'POST_RETIREMENT_HEALTH=FAIL'
echo 'AUDIT_RESULT=FAIL'
echo 'NEXT_ACTION=preserve_automation_boundaries_and_remediate_reported_failure'
exit 1
