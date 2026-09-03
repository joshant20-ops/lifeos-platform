#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
AUDIT="$PLATFORM/scripts/lifeos-legacy-dispatcher-retirement-audit.sh"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=/mnt/docker-data/automation/backups/dispatch-timer-retire-$STAMP
TARGETS=(lifeos-backlog-runner.timer lifeos-engineer-dispatcher.timer)
PROTECTED=(lifeos-control-job-submit.socket lifeos-root-broker.socket lifeos-autonomous-agent.service lifeos-engineer.service lifeos-ha-issue-queue-bridge.service)

fail(){ echo "ERROR: $*" >&2; exit 1; }
rollback(){
  echo 'ROLLBACK: restoring superseded timers'
  for u in "${TARGETS[@]}"; do systemctl enable --now "$u" >/dev/null 2>&1 || true; done
}
trap 'rc=$?; if (( rc != 0 )); then rollback; fi; exit $rc' EXIT

[[ $EUID -eq 0 ]] || fail 'run with sudo/root'
[[ -d "$PLATFORM/.git" ]] || fail 'platform repository missing'
HEAD=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || fail 'platform HEAD is not origin/main'
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || fail 'platform repository dirty'
[[ -x "$AUDIT" || -f "$AUDIT" ]] || fail 'retirement audit missing'

printf '%s\n' 'SUPERSEDED_DISPATCH_TIMER_RETIREMENT_VERSION=1'
printf 'PLATFORM_HEAD=%s\n' "$HEAD"
printf 'BACKUP=%s\n' "$BACKUP"
printf '%s\n' 'TARGETS=lifeos-backlog-runner.timer,lifeos-engineer-dispatcher.timer'
printf '%s\n' 'PROTECTED_UNITS_UNCHANGED=required'

echo
echo '==> GATE 0 — Re-prove retirement readiness'
AUDIT_OUT=$(runuser -u joshan -- bash "$AUDIT") || { printf '%s\n' "$AUDIT_OUT"; fail 'retirement audit failed'; }
printf '%s\n' "$AUDIT_OUT"
grep -qx 'LEGACY_DISPATCHER_RETIREMENT_READY=YES' <<<"$AUDIT_OUT" || fail 'retirement readiness not proven'
grep -qx 'SAFE_TO_DISABLE_NOW=lifeos-backlog-runner.timer,lifeos-engineer-dispatcher.timer' <<<"$AUDIT_OUT" || fail 'unexpected disable set'

for u in "${PROTECTED[@]}"; do
  [[ "$(systemctl is-active "$u" 2>/dev/null || true)" == active ]] || fail "protected unit not active before cutover: $u"
done

# Single-flight must be idle before removing schedulers.
python3 - <<'PY' || exit 1
import json, urllib.request
state=json.load(open('/var/lib/lifeos-backlog-runner/state.json'))
if state.get('active'):
    raise SystemExit('ERROR: backlog runner has active job')
with urllib.request.urlopen('http://127.0.0.1:8790/jobs',timeout=10) as r:
    data=json.load(r)
if isinstance(data,dict): data=data.get('jobs',data.get('items',[]))
active=[j for j in data if str(j.get('status','')).upper() in {'QUEUED','RUNNING'}]
if active:
    raise SystemExit('ERROR: Governor has active jobs')
print('SINGLE_FLIGHT_IDLE=PASS')
PY

mkdir -p "$BACKUP"
for u in "${TARGETS[@]}" "${PROTECTED[@]}"; do
  systemctl show "$u" -p ActiveState -p UnitFileState -p Result --no-pager > "$BACKUP/$u.before" 2>/dev/null || true
done
cp -a /var/lib/lifeos-backlog-runner/state.json "$BACKUP/backlog-state.before.json" 2>/dev/null || true

echo
echo '==> GATE 1 — Disable only superseded timers'
for u in "${TARGETS[@]}"; do
  systemctl disable --now "$u"
done

# Give systemd a moment to settle without inventing a long wait.
sleep 2

echo
echo '==> GATE 2 — Post-cutover invariants'
for u in "${TARGETS[@]}"; do
  active=$(systemctl is-active "$u" 2>/dev/null || true)
  enabled=$(systemctl is-enabled "$u" 2>/dev/null || true)
  printf '%s active=%s enabled=%s\n' "$u" "$active" "$enabled"
  [[ "$active" != active ]] || fail "$u still active"
  [[ "$enabled" == disabled ]] || fail "$u not disabled"
done

for u in "${PROTECTED[@]}"; do
  [[ "$(systemctl is-active "$u" 2>/dev/null || true)" == active ]] || fail "protected unit failed after cutover: $u"
  echo "PROTECTED_PASS=$u"
done

# Semaphore API and DB must remain healthy.
SEMAPHORE=$(docker ps --filter name='^/lifeos-semaphore-shadow-semaphore-1$' --format '{{.Names}}' | head -1)
DB=$(docker ps --filter name='^/lifeos-semaphore-shadow-semaphore-db-1$' --format '{{.Names}}' | head -1)
[[ -n "$SEMAPHORE" && -n "$DB" ]] || fail 'Semaphore containers missing'
[[ "$(docker inspect -f '{{.State.Status}}' "$SEMAPHORE")" == running ]] || fail 'Semaphore not running'
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$DB")" == healthy ]] || fail 'Semaphore DB not healthy'
BIND=$(docker port "$SEMAPHORE" 3000/tcp 2>/dev/null | head -1)
HOST=${BIND%:*}; PORT=${BIND##*:}; HOST=${HOST#[}; HOST=${HOST%]}
[[ -n "$HOST" && -n "$PORT" ]] || fail 'unable to determine Semaphore published endpoint'
curl -fsS --max-time 5 "http://${HOST}:${PORT}/api/ping" >/dev/null || fail 'Semaphore API failed after cutover'
echo 'SEMAPHORE_API=PASS'

# Ensure target service units were not disabled/deleted, only their timers.
for s in lifeos-backlog-runner.service lifeos-engineer-dispatcher.service; do
  state=$(systemctl is-enabled "$s" 2>/dev/null || true)
  [[ "$state" == static || "$state" == disabled || "$state" == indirect ]] || fail "unexpected service unit state: $s=$state"
done

trap - EXIT

echo
echo 'RESULT=PASS'
echo 'SUPERSEDED_DISPATCH_TIMERS_RETIRED=YES'
echo 'BACKLOG_RUNNER_TIMER_DISABLED=YES'
echo 'ENGINEER_DISPATCHER_TIMER_DISABLED=YES'
echo 'WORKER_TIMER_CHANGED=NO'
echo 'CONTROL_JOB_SOCKET_CHANGED=NO'
echo 'ROOT_BROKER_CHANGED=NO'
echo 'AUTONOMOUS_AGENT_CHANGED=NO'
echo 'ENGINEER_CHANGED=NO'
echo 'HA_ISSUE_QUEUE_BRIDGE_CHANGED=NO'
echo 'SEMAPHORE_API=PASS'
echo 'ROLLBACK=enable --now lifeos-backlog-runner.timer lifeos-engineer-dispatcher.timer'
printf 'BACKUP=%s\n' "$BACKUP"
echo 'NEXT_ACTION=audit_disabled_worker_and_retire_obsolete_dispatch_files_only_after_unique_responsibility_check'
