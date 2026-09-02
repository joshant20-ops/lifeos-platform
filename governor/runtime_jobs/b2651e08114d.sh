#!/usr/bin/env bash
set -euo pipefail

JOB_ID=b2651e08114d
REPO=/home/joshan/lifeos-platform
CONTROLLER="$REPO/homelab/live/usr/local/sbin/lifeos-transaction-controller"
ROLLBACK="$REPO/homelab/live/usr/local/sbin/lifeos-rollback"
SERVICE="$REPO/governor/systemd/lifeos-rollback@.service"
TIMER="$REPO/governor/systemd/lifeos-rollback@.timer"

fail() { printf 'RESULT=FAIL job=%s reason=%s\n' "$JOB_ID" "$1"; exit 1; }
[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman

for source in "$CONTROLLER" "$ROLLBACK" "$SERVICE" "$TIMER"; do
  [[ -f "$source" && ! -L "$source" ]] || fail unsafe_or_missing_source
done

install_protected() {
  local source=$1 destination=$2 mode=$3
  if [[ -e "$destination" ]]; then
    cmp -s "$source" "$destination" || fail protected_core_differs_requires_staged_upgrade
  else
    timeout 15 install -o root -g root -m "$mode" "$source" "$destination"
  fi
  [[ "$(stat -c '%U:%G:%a' "$destination")" == "root:root:$mode" ]] || fail ownership_or_mode
}

install -d -o root -g root -m 700 /var/lib/lifeos-transactions
install -d -o root -g root -m 755 /usr/local/sbin /etc/systemd/system /etc/lifeos-control
install_protected "$CONTROLLER" /usr/local/sbin/lifeos-transaction-controller 755
install_protected "$ROLLBACK" /usr/local/sbin/lifeos-rollback 755
install_protected "$SERVICE" /etc/systemd/system/lifeos-rollback@.service 644
install_protected "$TIMER" /etc/systemd/system/lifeos-rollback@.timer 644
timeout 30 systemctl daemon-reload
timeout 30 systemd-analyze verify /etc/systemd/system/lifeos-rollback@.service /etc/systemd/system/lifeos-rollback@.timer
timeout 60 python3 -m pytest -q "$REPO/tests/test_transaction_controller.py"
printf 'PROTECTED_CORE=PASS owner=root modes=755,644\n'
printf 'WATCHDOG_UNITS=PASS controller_independent=true reboot_persistent_instance=true\n'
printf 'AUTOMATED_TESTS=PASS suite=tests/test_transaction_controller.py\n'
printf 'RESULT=PASS job=%s\n' "$JOB_ID"
