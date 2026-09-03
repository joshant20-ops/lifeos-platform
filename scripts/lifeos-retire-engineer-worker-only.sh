#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
WORKER=/home/joshan/automation/queues/lifeos_engineer_worker.py
WORKER_SERVICE=/etc/systemd/system/lifeos-engineer-worker.service
WORKER_TIMER=/etc/systemd/system/lifeos-engineer-worker.timer
DISPATCHER_SERVICE=/etc/systemd/system/lifeos-engineer-dispatcher.service
DISPATCHER_TIMER=/etc/systemd/system/lifeos-engineer-dispatcher.timer
QUEUE=/home/joshan/automation/queues/engineer_job_queue.jsonl
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=/mnt/docker-data/automation/backups/engineer-worker-retire-$STAMP

fail(){ echo "ERROR: $*" >&2; exit 1; }
trap 'rc=$?; if (( rc != 0 )); then echo "FAILED rc=$rc"; echo "Recovery bundle: $BACKUP"; fi' EXIT

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo'
[[ -d "$PLATFORM/.git" ]] || fail 'platform repo missing'

HEAD=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || fail 'platform HEAD must equal origin/main'
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || fail 'platform repo dirty'

echo 'ENGINEER_WORKER_RETIREMENT_VERSION=1'
echo "PLATFORM_HEAD=$HEAD"
echo "BACKUP=$BACKUP"
echo 'TARGET=lifeos-engineer-worker only'
echo

echo '==> GATE 0 — Re-prove worker retirement readiness'
AUDIT=$(runuser -u joshan -- bash "$PLATFORM/scripts/lifeos-worker-dispatcher-split-audit.sh")
printf '%s\n' "$AUDIT"
grep -qx 'WORKER_RETIREMENT_READY=YES' <<<"$AUDIT" || fail 'worker retirement not ready'
grep -qx 'DISPATCHER_FILE_RETIREMENT_READY=NO' <<<"$AUDIT" || fail 'dispatcher preservation invariant absent'

[[ "$(systemctl is-active lifeos-engineer-worker.timer 2>/dev/null || true)" != active ]] || fail 'worker timer unexpectedly active'
[[ "$(systemctl is-active lifeos-engineer-dispatcher.timer 2>/dev/null || true)" != active ]] || fail 'dispatcher timer unexpectedly active'

# Independently confirm there is no pending queue work.
PENDING=$(python3 - "$QUEUE" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
n=0
if p.exists():
    for line in p.read_text(errors='replace').splitlines():
        try: d=json.loads(line)
        except Exception: continue
        n += str(d.get('status','')).lower() == 'pending'
print(n)
PY
)
[[ "$PENDING" == 0 ]] || fail "pending engineer queue work exists: $PENDING"
echo 'PENDING_QUEUE=0'

# Protected replacement boundaries must be up before removing the dead worker.
for u in lifeos-control-job-submit.socket lifeos-root-broker.socket lifeos-autonomous-agent.service lifeos-engineer.service lifeos-ha-issue-queue-bridge.service; do
  [[ "$(systemctl is-active "$u" 2>/dev/null || true)" == active ]] || fail "protected unit inactive: $u"
done

echo
mkdir -p "$BACKUP"
for p in "$WORKER" "$WORKER_SERVICE" "$WORKER_TIMER"; do
  [[ -e "$p" ]] || fail "expected worker artifact missing: $p"
  cp -a --parents "$p" "$BACKUP/"
done
systemctl status lifeos-engineer-worker.timer lifeos-engineer-worker.service --no-pager >"$BACKUP/systemd-worker-status.before.txt" 2>&1 || true
systemctl status lifeos-engineer-dispatcher.timer lifeos-engineer-dispatcher.service --no-pager >"$BACKUP/systemd-dispatcher-status.before.txt" 2>&1 || true

echo '==> GATE 1 — Retire worker artifacts only'
systemctl disable --now lifeos-engineer-worker.timer >/dev/null 2>&1 || true
rm -f "$WORKER_TIMER" "$WORKER_SERVICE" "$WORKER"
systemctl daemon-reload
systemctl reset-failed lifeos-engineer-worker.service lifeos-engineer-worker.timer >/dev/null 2>&1 || true

# Worker must be gone.
[[ ! -e "$WORKER" && ! -e "$WORKER_SERVICE" && ! -e "$WORKER_TIMER" ]] || fail 'worker artifacts still exist'
[[ "$(systemctl is-active lifeos-engineer-worker.timer 2>/dev/null || true)" != active ]] || fail 'worker timer active after retirement'

# Dispatcher capability remains intentionally preserved, but disabled.
[[ -e "$DISPATCHER_SERVICE" && -e "$DISPATCHER_TIMER" ]] || fail 'dispatcher units were disturbed'
[[ -e /home/joshan/automation/queues/lifeos_engineer_dispatcher.py ]] || fail 'dispatcher implementation disturbed'
[[ -e /home/joshan/automation/queues/lifeos_engineer_maintenance.py ]] || fail 'maintenance capability disturbed'
[[ "$(systemctl is-active lifeos-engineer-dispatcher.timer 2>/dev/null || true)" != active ]] || fail 'dispatcher timer unexpectedly active'

# Protected boundaries remain live.
for u in lifeos-control-job-submit.socket lifeos-root-broker.socket lifeos-autonomous-agent.service lifeos-engineer.service lifeos-ha-issue-queue-bridge.service; do
  [[ "$(systemctl is-active "$u" 2>/dev/null || true)" == active ]] || fail "protected unit failed after retirement: $u"
done

# Semaphore remains reachable from host.
BIND=$(docker inspect lifeos-semaphore-shadow-semaphore-1 --format '{{range $p,$v := .NetworkSettings.Ports}}{{if eq $p "3000/tcp"}}{{(index $v 0).HostIp}}:{{(index $v 0).HostPort}}{{end}}{{end}}' 2>/dev/null || true)
[[ -n "$BIND" ]] || fail 'unable to derive Semaphore published bind'
curl -fsS --max-time 5 "http://$BIND/api/ping" >/dev/null || fail 'Semaphore API unavailable after worker retirement'

echo
echo 'RESULT=PASS'
echo 'ENGINEER_WORKER_RETIRED=YES'
echo 'WORKER_FILE_REMOVED=YES'
echo 'WORKER_SERVICE_REMOVED=YES'
echo 'WORKER_TIMER_REMOVED=YES'
echo 'PENDING_QUEUE=0'
echo 'DISPATCHER_FILES_CHANGED=NO'
echo 'DISPATCHER_TIMER_STATE=disabled'
echo 'SELF_MAINTENANCE_CAPABILITY_PRESERVED=YES'
echo 'ROOT_BROKER_CHANGED=NO'
echo 'AUTONOMOUS_AGENT_CHANGED=NO'
echo 'ENGINEER_CHANGED=NO'
echo 'SEMAPHORE_API=PASS'
echo "BACKUP=$BACKUP"
echo 'NEXT_ACTION=build_and_prove_semaphore_autonomy_canary_and_engineer_self_maintenance_templates_before_dispatcher_file_retirement'
