#!/usr/bin/env bash
set -euo pipefail

readonly JOB_ID=ba97eb7c1221
readonly REPO=/home/joshan/lifeos-platform
readonly SUITE="$REPO/tests/test_transaction_controller.py"

fail() {
  printf 'ISSUE_VALIDITY=VALID\n'
  printf 'LIFEOS_WORK_STATE=BLOCKED\n'
  printf 'BARRIER=%s\n' "$1"
  printf 'NEXT_AUTONOMOUS_ACTION=repair the failed protected transaction-core check and rerun this Watchman job\n'
  printf 'DISCOVERED_ISSUES_JSON_B64=none\n'
  printf 'RESULT=FAIL job=%s reason=%s\n' "$JOB_ID" "$1"
  exit 1
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
[[ -f "$SUITE" && ! -L "$SUITE" ]] || fail unsafe_or_missing_test_suite
[[ -x /usr/local/sbin/lifeos-transaction-controller ]] || fail protected_controller_not_installed
[[ -x /usr/local/sbin/lifeos-rollback ]] || fail protected_rollback_not_installed
[[ "$(stat -c '%U:%G:%a' /var/lib/lifeos-transactions)" == root:root:700 ]] || fail unsafe_transaction_state_permissions
timeout 30s systemd-analyze verify /etc/systemd/system/lifeos-rollback@.service /etc/systemd/system/lifeos-rollback@.timer || fail watchdog_unit_verification
grep -Fxq 'OnActiveSec=2h' /etc/systemd/system/lifeos-rollback@.timer || fail watchdog_deadline_not_two_hours
grep -Fxq 'Persistent=true' /etc/systemd/system/lifeos-rollback@.timer || fail watchdog_not_persistent
timeout 90s python3 -m pytest -q "$SUITE" || fail scoped_transaction_tests

printf 'ISSUE_VALIDITY=VALID\n'
printf 'LIFEOS_WORK_STATE=PASS\n'
printf 'BARRIER=none\n'
printf 'NEXT_AUTONOMOUS_ACTION=route one existing bounded broker deployment through the protected controller with service-state recovery\n'
printf 'DISCOVERED_ISSUES_JSON_B64=none\n'
printf 'PROTECTED_CORE=PASS owner=root state_mode=700\n'
printf 'WATCHDOG=PASS independent=true deadline=2h persistent=true\n'
printf 'DEADLINE_RACE=PASS late_commit=rolled_back\n'
printf 'RESULT=PASS job=%s\n' "$JOB_ID"
printf 'TESTS=transaction controller scoped suite and installed systemd units PASS\n'
printf 'NEXT_RUNTIME_CHECK=route one bounded broker deployment through the controller with service-state recovery\n'
