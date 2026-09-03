#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
DISPATCHER=/home/joshan/automation/queues/lifeos_engineer_dispatcher.py
MAINT=/home/joshan/automation/queues/lifeos_engineer_maintenance.py
QUEUE=/home/joshan/automation/queues/engineer_job_queue.jsonl
SERVICE=/etc/systemd/system/lifeos-engineer-dispatcher.service
TIMER=/etc/systemd/system/lifeos-engineer-dispatcher.timer
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=/mnt/docker-data/automation/backups/engineer-dispatcher-retire-$STAMP
SEMAPHORE_BASE=${SEMAPHORE_BASE:-http://192.168.0.203:3000/api}

fail(){ echo "ERROR: $*" >&2; exit 1; }
rollback(){
  echo 'ROLLBACK=attempting dispatcher artifact restore' >&2
  if [[ -d "$BACKUP" ]]; then
    [[ -f "$BACKUP/lifeos_engineer_dispatcher.py" ]] && install -o joshan -g joshan -m 0755 "$BACKUP/lifeos_engineer_dispatcher.py" "$DISPATCHER"
    [[ -f "$BACKUP/lifeos_engineer_maintenance.py" ]] && install -o joshan -g joshan -m 0755 "$BACKUP/lifeos_engineer_maintenance.py" "$MAINT"
    [[ -f "$BACKUP/lifeos-engineer-dispatcher.service" ]] && install -o root -g root -m 0644 "$BACKUP/lifeos-engineer-dispatcher.service" "$SERVICE"
    [[ -f "$BACKUP/lifeos-engineer-dispatcher.timer" ]] && install -o root -g root -m 0644 "$BACKUP/lifeos-engineer-dispatcher.timer" "$TIMER"
    systemctl daemon-reload || true
  fi
}
trap 'rc=$?; if (( rc != 0 )); then rollback; fi; exit $rc' EXIT

runj(){ runuser -u joshan -- env -i HOME=/home/joshan PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 "$@"; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher retirement must run as root'
echo 'ENGINEER_DISPATCHER_RETIREMENT_VERSION=3'
echo "PLATFORM_HEAD=$(runj git -C "$PLATFORM" rev-parse HEAD)"
echo "BACKUP=$BACKUP"
echo 'TARGET=legacy engineer dispatcher and dedicated maintenance helper only'

echo
echo '==> GATE 0 — Re-prove replacement capabilities'
# Version 6 proof intentionally runs as root for root-owned runtime staging, while
# all repository Git reads inside it are explicitly dropped to joshan.
PROOF=$(bash "$PLATFORM/scripts/lifeos-semaphore-dispatcher-capability-proof.sh") || { echo "$PROOF"; fail 'Semaphore dispatcher capability proof failed'; }
echo "$PROOF"
grep -qx 'RESULT=PASS' <<<"$PROOF" || fail 'capability proof missing RESULT=PASS'
grep -qx 'SEMAPHORE_AUTONOMY_CANARY=PASS' <<<"$PROOF" || fail 'canary replacement not proven'
grep -qx 'SEMAPHORE_ENGINEER_SELF_MAINTENANCE=PASS' <<<"$PROOF" || fail 'maintenance replacement not proven'

[[ "$(systemctl is-active lifeos-engineer-dispatcher.timer 2>/dev/null || true)" == inactive ]] || fail 'dispatcher timer must be inactive'
[[ "$(systemctl is-enabled lifeos-engineer-dispatcher.timer 2>/dev/null || true)" == disabled ]] || fail 'dispatcher timer must be disabled'
[[ "$(systemctl is-active lifeos-engineer-dispatcher.service 2>/dev/null || true)" != active ]] || fail 'dispatcher service unexpectedly active'

pending=0
if [[ -f "$QUEUE" ]]; then
  pending=$(runj python3 - "$QUEUE" <<'PY'
import json,sys
n=0
for line in open(sys.argv[1], encoding='utf-8'):
    line=line.strip()
    if not line: continue
    try: d=json.loads(line)
    except Exception: continue
    if d.get('status') == 'pending' and d.get('job_type') in {'autonomy_canary','engineer_self_maintenance'}:
        n += 1
print(n)
PY
)
fi
echo "PENDING_DISPATCHER_JOBS=$pending"
[[ "$pending" == 0 ]] || fail 'pending legacy dispatcher work exists'
for p in "$DISPATCHER" "$MAINT" "$SERVICE" "$TIMER"; do [[ -e "$p" ]] || fail "expected retirement artifact missing: $p"; done

curl -fsS "$SEMAPHORE_BASE/ping" >/dev/null || curl -fsS "${SEMAPHORE_BASE%/api}/api/ping" >/dev/null || fail 'Semaphore API unavailable'
for u in lifeos-control-job-submit.socket lifeos-root-broker.socket lifeos-autonomous-agent.service lifeos-engineer.service lifeos-ha-issue-queue-bridge.service; do
  [[ "$(systemctl is-active "$u" 2>/dev/null || true)" == active ]] || fail "protected unit not active before retirement: $u"
done

BEFORE_HEAD=$(runj git -C "$PLATFORM" rev-parse HEAD)
BEFORE_STATUS=$(runj git -C "$PLATFORM" status --porcelain)
mkdir -p "$BACKUP"
cp -a "$DISPATCHER" "$BACKUP/lifeos_engineer_dispatcher.py"
cp -a "$MAINT" "$BACKUP/lifeos_engineer_maintenance.py"
cp -a "$SERVICE" "$BACKUP/lifeos-engineer-dispatcher.service"
cp -a "$TIMER" "$BACKUP/lifeos-engineer-dispatcher.timer"
[[ -f "$QUEUE" ]] && cp -a "$QUEUE" "$BACKUP/engineer_job_queue.jsonl"

echo
echo '==> GATE 1 — Retire dispatcher artifacts'
systemctl stop lifeos-engineer-dispatcher.service 2>/dev/null || true
systemctl disable lifeos-engineer-dispatcher.timer 2>/dev/null || true
rm -f "$SERVICE" "$TIMER" "$DISPATCHER" "$MAINT"
systemctl daemon-reload
systemctl reset-failed lifeos-engineer-dispatcher.service 2>/dev/null || true
[[ ! -e "$DISPATCHER" && ! -e "$MAINT" && ! -e "$SERVICE" && ! -e "$TIMER" ]] || fail 'one or more dispatcher artifacts still exist'
if systemctl list-unit-files --no-pager | grep -q '^lifeos-engineer-dispatcher\.timer'; then fail 'dispatcher timer still registered'; fi
if systemctl list-unit-files --no-pager | grep -q '^lifeos-engineer-dispatcher\.service'; then fail 'dispatcher service still registered'; fi

for u in lifeos-control-job-submit.socket lifeos-root-broker.socket lifeos-autonomous-agent.service lifeos-engineer.service lifeos-ha-issue-queue-bridge.service; do
  [[ "$(systemctl is-active "$u" 2>/dev/null || true)" == active ]] || fail "protected unit failed after retirement: $u"
  echo "PROTECTED_PASS=$u"
done
curl -fsS "$SEMAPHORE_BASE/ping" >/dev/null || curl -fsS "${SEMAPHORE_BASE%/api}/api/ping" >/dev/null || fail 'Semaphore API failed after retirement'
AFTER_HEAD=$(runj git -C "$PLATFORM" rev-parse HEAD)
AFTER_STATUS=$(runj git -C "$PLATFORM" status --porcelain)
[[ "$AFTER_HEAD" == "$BEFORE_HEAD" ]] || fail 'platform HEAD changed'
[[ "$AFTER_STATUS" == "$BEFORE_STATUS" ]] || fail 'platform worktree changed'

trap - EXIT
echo
echo 'RESULT=PASS'
echo 'ENGINEER_DISPATCHER_RETIRED=YES'
echo 'DISPATCHER_FILE_REMOVED=YES'
echo 'MAINTENANCE_HELPER_REMOVED=YES'
echo 'DISPATCHER_SERVICE_REMOVED=YES'
echo 'DISPATCHER_TIMER_REMOVED=YES'
echo 'PENDING_DISPATCHER_JOBS=0'
echo 'SEMAPHORE_AUTONOMY_CANARY=PASS'
echo 'SEMAPHORE_ENGINEER_SELF_MAINTENANCE=PASS'
echo 'CONTROL_JOB_SOCKET_CHANGED=NO'
echo 'ROOT_BROKER_CHANGED=NO'
echo 'AUTONOMOUS_AGENT_CHANGED=NO'
echo 'ENGINEER_CHANGED=NO'
echo 'HA_ISSUE_QUEUE_BRIDGE_CHANGED=NO'
echo 'SEMAPHORE_API=PASS'
echo 'PLATFORM_MUTATION=NONE'
echo "BACKUP=$BACKUP"
echo 'NEXT_ACTION=audit stale platform references and prove GitHub runner deployment loop'
