#!/usr/bin/env bash
set -Eeuo pipefail

BASE=/home/joshan/automation
QUEUE="$BASE/queues/engineer_job_queue.jsonl"
WORKER="$BASE/queues/lifeos_engineer_worker.py"
DISPATCHER="$BASE/queues/lifeos_engineer_dispatcher.py"
MAINT="$BASE/queues/lifeos_engineer_maintenance.py"

printf '%s\n' 'WORKER_DISPATCHER_SPLIT_AUDIT_VERSION=1'
printf '%s\n' 'MUTATIONS=NONE'
printf 'PLATFORM_HEAD=%s\n' "$(git -C /home/joshan/lifeos-platform rev-parse HEAD)"

echo
echo '=== UNIT STATE ==='
for u in \
  lifeos-engineer-worker.timer lifeos-engineer-worker.service \
  lifeos-engineer-dispatcher.timer lifeos-engineer-dispatcher.service; do
  printf '%-40s active=%-10s enabled=%s\n' "$u" \
    "$(systemctl is-active "$u" 2>/dev/null || true)" \
    "$(systemctl is-enabled "$u" 2>/dev/null || true)"
done

echo
echo '=== QUEUE CLASSIFICATION ==='
python3 - "$QUEUE" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
counts={}
pending={}
total=0
if p.exists():
    for line in p.read_text(errors='replace').splitlines():
        if not line.strip(): continue
        total += 1
        try: d=json.loads(line)
        except Exception:
            counts['<invalid>']=counts.get('<invalid>',0)+1
            pending['<invalid>']=pending.get('<invalid>',0)+1
            continue
        typ=str(d.get('job_type') or '<missing>')
        counts[typ]=counts.get(typ,0)+1
        if str(d.get('status') or '').lower() == 'pending':
            pending[typ]=pending.get(typ,0)+1
print(f'QUEUE_PRESENT={"yes" if p.exists() else "no"}')
print(f'QUEUE_TOTAL={total}')
for k in sorted(counts): print(f'QUEUE_TYPE_{k}={counts[k]}')
print(f'PENDING_TOTAL={sum(pending.values())}')
for k in sorted(pending): print(f'PENDING_TYPE_{k}={pending[k]}')
worker_pending=sum(v for k,v in pending.items() if k in {'service_check','failure_review'})
dispatch_pending=sum(v for k,v in pending.items() if k in {'autonomy_canary','engineer_self_maintenance'})
unknown_pending=sum(v for k,v in pending.items() if k not in {'service_check','failure_review','autonomy_canary','engineer_self_maintenance'})
print(f'WORKER_ONLY_PENDING={worker_pending}')
print(f'DISPATCHER_ONLY_PENDING={dispatch_pending}')
print(f'UNKNOWN_PENDING={unknown_pending}')
PY

echo
echo '=== FILE PRESENCE ==='
for f in "$WORKER" "$DISPATCHER" "$MAINT"; do
  if [[ -e "$f" ]]; then
    stat -c 'present=yes owner=%U group=%G mode=%a bytes=%s path=%n' "$f"
  else
    echo "present=no path=$f"
  fi
done

echo
echo '=== DISPATCHER UNIQUE CAPABILITY SIGNALS ==='
if [[ -f "$DISPATCHER" ]]; then
  grep -nE 'ALLOWED_TYPES|autonomy_canary|engineer_self_maintenance|lifeos_engineer_maintenance|subprocess\.run|execute_canary|execute_maintenance' "$DISPATCHER" || true
fi

echo
echo '=== MAINTENANCE CAPABILITY SIGNALS ==='
if [[ -f "$MAINT" ]]; then
  grep -nE 'def |subprocess|systemctl|docker|git|restart|update|install|maintenance|health|backup|rollback' "$MAINT" | head -160 || true
fi

echo
echo '=== REPOSITORY RETIREMENT DECISION ==='
if [[ -f /home/joshan/lifeos-platform/architecture/decisions/engineer-worker-retirement.md ]]; then
  sed -n '1,120p' /home/joshan/lifeos-platform/architecture/decisions/engineer-worker-retirement.md
fi

echo
echo '=== CLASSIFICATION ==='
worker_active=$(systemctl is-active lifeos-engineer-worker.timer 2>/dev/null || true)
dispatch_active=$(systemctl is-active lifeos-engineer-dispatcher.timer 2>/dev/null || true)
readarray -t q < <(python3 - "$QUEUE" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]); wp=dp=up=0
if p.exists():
  for line in p.read_text(errors='replace').splitlines():
    if not line.strip(): continue
    try:d=json.loads(line)
    except Exception: up+=1; continue
    if str(d.get('status') or '').lower()!='pending': continue
    t=str(d.get('job_type') or '')
    if t in {'service_check','failure_review'}: wp+=1
    elif t in {'autonomy_canary','engineer_self_maintenance'}: dp+=1
    else: up+=1
print(wp); print(dp); print(up)
PY
)
wp=${q[0]:-0}; dp=${q[1]:-0}; up=${q[2]:-0}

if [[ "$worker_active" == inactive && "$wp" == 0 && "$up" == 0 ]]; then
  echo 'WORKER_RETIREMENT_READY=YES'
  echo 'WORKER_DECISION=RETIRE_FILE_AND_UNITS_CANDIDATE'
else
  echo 'WORKER_RETIREMENT_READY=NO'
  echo "WORKER_BLOCKER=timer_state_${worker_active}_worker_pending_${wp}_unknown_pending_${up}"
fi

if [[ "$dispatch_active" == inactive ]]; then
  echo 'DISPATCHER_RUNTIME_STATE=SAFELY_DISABLED'
else
  echo 'DISPATCHER_RUNTIME_STATE=ACTIVE_UNEXPECTEDLY'
fi

if [[ -f "$MAINT" ]]; then
  echo 'DISPATCHER_FILE_RETIREMENT_READY=NO'
  echo 'DISPATCHER_BLOCKER=self_maintenance_capability_not_yet_proven_in_semaphore'
  echo 'NEXT_ACTION=retire_worker_only_then_build_semaphore_canary_and_self_maintenance_templates_before_dispatcher_file_retirement'
else
  echo 'DISPATCHER_FILE_RETIREMENT_READY=REQUIRES_REVIEW'
  echo 'NEXT_ACTION=review_missing_maintenance_helper_before_dispatcher_file_retirement'
fi

echo 'AUDIT_RESULT=PASS'
