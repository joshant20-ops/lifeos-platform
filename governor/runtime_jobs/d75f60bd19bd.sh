#!/usr/bin/env bash
set -euo pipefail

readonly REPO=/home/joshan/lifeos-platform
fail() {
  printf 'ISSUE_VALIDITY=VALID\nLIFEOS_WORK_STATE=BLOCKED\nBARRIER=%s\n' "$1"
  printf 'NEXT_AUTONOMOUS_ACTION=repair the protected watchdog candidate and rerun through Watchman\n'
  printf 'DISCOVERED_ISSUES_JSON_B64=none\nRESULT=FAIL reason=%s\n' "$1"
  exit 1
}
[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
timeout 90s python3 -m pytest -q "$REPO/tests/test_transaction_controller.py" || fail scoped_tests
timeout 15s systemd-analyze verify "$REPO/governor/systemd/lifeos-rollback@.service" "$REPO/governor/systemd/lifeos-rollback@.timer" || fail watchdog_units
grep -Fq 'OnBootSec=1min' "$REPO/governor/systemd/lifeos-rollback@.timer" || fail boot_poll_missing
grep -Fq 'OnUnitActiveSec=1min' "$REPO/governor/systemd/lifeos-rollback@.timer" || fail recurring_poll_missing
grep -Fq ' --expired %i' "$REPO/governor/systemd/lifeos-rollback@.service" || fail deadline_gate_missing
printf 'ISSUE_VALIDITY=VALID\nLIFEOS_WORK_STATE=PASS\nBARRIER=none\n'
printf 'NEXT_AUTONOMOUS_ACTION=stage this protected-core change with the old recovery path retained, then prove expiry across a Pi5 reboot\n'
printf 'DISCOVERED_ISSUES_JSON_B64=none\nWATCHDOG_REBOOT_SEMANTICS=PASS durable_deadline=true\n'
printf 'RESULT=PASS\nTESTS=scoped controller tests and systemd unit verification PASS\n'
printf 'NEXT_RUNTIME_CHECK=A/B deploy protected core and prove an overdue canary rolls back after Pi5 reboot\n'
