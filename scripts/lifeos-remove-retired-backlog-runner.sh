#!/usr/bin/env bash
# #797 final retirement: remove only the inert legacy backlog runner runtime.
# Historical state is deliberately preserved because Semaphore transition
# observers still consume it; state migration is a separate serial purge item.
set -Eeuo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'RESULT=FAIL'; echo 'REASON=root_required'; exit 1; }
systemctl disable --now lifeos-backlog-runner.timer >/dev/null 2>&1 || true
systemctl stop lifeos-backlog-runner.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/lifeos-backlog-runner.timer
rm -f /etc/systemd/system/lifeos-backlog-runner.service
rm -f /usr/local/libexec/lifeos-backlog-runner
systemctl daemon-reload
[[ "$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)" != active ]]
[[ "$(systemctl is-active lifeos-backlog-runner.service 2>/dev/null || true)" != active ]]
[[ "$(systemctl is-enabled lifeos-backlog-runner.timer 2>/dev/null || true)" == not-found ]]
[[ ! -e /usr/local/libexec/lifeos-backlog-runner ]]
[[ -r /var/lib/lifeos-backlog-runner/state.json ]]
echo 'LEGACY_BACKLOG_EXECUTABLE=REMOVED'
echo 'LEGACY_BACKLOG_TIMER=REMOVED'
echo 'LEGACY_BACKLOG_SERVICE=REMOVED'
echo 'BACKLOG_TRANSITION_STATE=PRESERVED'
echo 'RESULT=PASS'
