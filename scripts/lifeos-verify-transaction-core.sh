#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO=/home/joshan/lifeos-platform
readonly SUITE="$REPO/tests/test_transaction_controller.py"

fail() {
  printf 'TRANSACTION_CORE_VERIFY=FAIL\n'
  printf 'BARRIER=%s\n' "$1"
  exit 1
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_gateway
[[ -f "$SUITE" && ! -L "$SUITE" ]] || fail unsafe_or_missing_test_suite
[[ -x /usr/local/sbin/lifeos-transaction-controller ]] || fail protected_controller_not_installed
[[ -x /usr/local/sbin/lifeos-rollback ]] || fail protected_rollback_not_installed
[[ "$(stat -c '%U:%G:%a' /var/lib/lifeos-transactions)" == root:root:700 ]] || fail unsafe_transaction_state_permissions

timeout 30s systemd-analyze verify \
  /etc/systemd/system/lifeos-rollback@.service \
  /etc/systemd/system/lifeos-rollback@.timer || fail watchdog_unit_verification

grep -Fxq 'OnActiveSec=2h' /etc/systemd/system/lifeos-rollback@.timer || fail watchdog_deadline_not_two_hours
grep -Fxq 'Persistent=true' /etc/systemd/system/lifeos-rollback@.timer || fail watchdog_not_persistent

timeout 90s python3 -m pytest -q "$SUITE" || fail scoped_transaction_tests

printf '%s\n' \
  'TRANSACTION_CORE_VERIFY=PASS' \
  'PROTECTED_CORE=PASS' \
  'WATCHDOG=PASS' \
  'WATCHDOG_DEADLINE=2h' \
  'WATCHDOG_PERSISTENT=true' \
  'SCOPED_TRANSACTION_TESTS=PASS' \
  'BARRIER=none'
