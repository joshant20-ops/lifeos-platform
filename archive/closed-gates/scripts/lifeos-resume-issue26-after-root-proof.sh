#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO=/home/joshan/lifeos-platform
readonly STATE=/var/lib/lifeos-backlog-runner/state.json

fail() {
  printf 'ISSUE26_RESUME=FAIL\n'
  printf 'BARRIER=%s\n' "$1"
  exit 1
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_gateway

# Re-prove the exact privileged path before modifying scheduler state.
out="$(bash "$REPO/scripts/lifeos-verify-transaction-core.sh" 2>&1)" || {
  printf '%s\n' "$out"
  fail transaction_core_verification_failed
}
printf '%s\n' "$out"
grep -qx 'TRANSACTION_CORE_VERIFY=PASS' <<<"$out" || fail transaction_core_not_proven

[[ -f "$STATE" && ! -L "$STATE" ]] || fail backlog_state_missing_or_unsafe

python3 - "$STATE" <<'PY'
import json, os, sys, tempfile
from pathlib import Path

path = Path(sys.argv[1])
st = path.stat()
data = json.loads(path.read_text())
active = data.get('active')
if active:
    raise SystemExit('ERROR=backlog_has_active_job')
issues = data.setdefault('issues', {})
entry = issues.get('26')
if not isinstance(entry, dict):
    raise SystemExit('ERROR=issue26_state_missing')
barrier = str(entry.get('barrier') or '')
if 'must_run_as_root_via_Watchman' not in barrier:
    raise SystemExit('ERROR=issue26_barrier_changed:' + barrier[:160])
entry['retry_after'] = None
entry['work_state'] = 'IN_PROGRESS'
entry['issue_validity'] = 'VALID'
entry['barrier'] = 'none'
entry['next_autonomous_action'] = 'resume blocked target recovery through governed root/transaction path'
entry['root_barrier_cleared_by'] = 'verify-transaction-core'
fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', dir=str(path.parent))
try:
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.chown(tmp_name, st.st_uid, st.st_gid)
    os.chmod(tmp_name, st.st_mode & 0o7777)
    os.replace(tmp_name, path)
finally:
    try:
        os.unlink(tmp_name)
    except FileNotFoundError:
        pass
print('ISSUE26_STATE_RECONCILED=PASS')
PY

systemctl start lifeos-backlog-runner.service || fail backlog_runner_start_failed
systemctl is-failed --quiet lifeos-backlog-runner.service && fail backlog_runner_failed

# The HA bridge refreshes retained control state on its own. Wait boundedly until
# it no longer advertises the barrier that has just been independently cleared.
for _ in $(seq 1 12); do
  control="$(timeout 5s mosquitto_sub -h 127.0.0.1 -C 1 -t lifeos/issue_queue/control 2>/dev/null || true)"
  if [[ -n "$control" ]] && python3 - "$control" <<'PY'
import json, sys
v=json.loads(sys.argv[1])
if str(v.get('blocker') or '') == 'must_run_as_root_via_Watchman':
    raise SystemExit(1)
print('CONTROL_STATE_AFTER_RESUME=' + str(v.get('state') or 'UNKNOWN'))
print('CONTROL_ISSUE_AFTER_RESUME=' + str(v.get('current_issue') or 'none'))
print('CONTROL_BLOCKER_AFTER_RESUME=' + str(v.get('blocker') or 'none'))
PY
  then
    printf '%s\n' \
      'ISSUE26_RESUME=PASS' \
      'ROOT_BARRIER_CLEARED=PASS' \
      'BACKLOG_RUNNER_RESUMED=PASS' \
      'BARRIER=none'
    exit 0
  fi
  sleep 5
done

fail control_state_did_not_advance
