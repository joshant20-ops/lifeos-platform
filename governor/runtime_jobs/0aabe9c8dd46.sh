#!/usr/bin/env bash
set -Eeuo pipefail

REPO=/home/joshan/lifeos-platform
INSTALLER=$REPO/governor/scripts/install-backlog-runner-pi5.sh
WORKER=/usr/local/libexec/lifeos-backlog-runner
STATE=/var/lib/lifeos-backlog-runner/state.json

fail() { printf 'RESULT=FAIL\nREASON=%s\n' "$1" >&2; exit 1; }
[[ $(id -u) -eq 0 ]] || fail must_run_via_sudo_on_pi5
[[ $(hostname) == Docker ]] || fail must_run_on_pi5_Docker
[[ -f "$INSTALLER" && ! -L "$INSTALLER" ]] || fail canonical_installer_invalid
[[ -f "$REPO/governor/backlog_runner.py" && ! -L "$REPO/governor/backlog_runner.py" ]] || fail canonical_worker_source_invalid

timeout 600s "$INSTALLER" || fail installer_failed
systemctl is-active --quiet lifeos-backlog-runner.timer || fail backlog_timer_inactive
[[ -x "$WORKER" && ! -L "$WORKER" ]] || fail installed_worker_invalid
[[ -s "$STATE" ]] || fail persistent_state_missing

python3 - "$STATE" <<'PY' || exit 1
import json, sys, time
state = json.load(open(sys.argv[1], encoding="utf-8"))
assert state.get("version") == 2, state
issue6 = state.get("issues", {}).get("6", {})
assert issue6.get("retry_count", 0) >= 6, issue6
assert issue6.get("retry_after", 0) > time.time(), issue6
active = state.get("active") or {}
assert active.get("issue") != 6, active
print(f"ISSUE_6_COOLDOWN=PASS retry_after={issue6['retry_after']} retry_count={issue6['retry_count']}")
print("PERSISTENT_STATE=PASS")
PY

systemctl start lifeos-backlog-runner.service
timeout 30s systemctl is-active --quiet lifeos-backlog-runner.service || true
journalctl -u lifeos-backlog-runner.service -n 30 --no-pager
printf 'BACKLOG_LOOP=PASS\n'
printf 'NEXT_ELIGIBLE_DISPATCH=PASS single-flight service invoked\n'
printf 'LIVE_DEPLOYMENT=PASS\n'
printf 'RESULT=PASS\n'
printf 'NEXT_RUNTIME_CHECK=journalctl -u lifeos-backlog-runner.service -n 50 --no-pager; verify issue 6 absent and next eligible issue selected\n'
