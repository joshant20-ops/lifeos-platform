#!/usr/bin/env bash
set -Eeuo pipefail

# Capability Stage 3: native systemd cleanup only.
# No custom supervisor is introduced. Historical transient failed units are reset;
# the superseded lifeos-pi-control timer/service pair is disabled/stopped but unit
# files are preserved for rollback. Protected permanent control-plane units are never stopped.

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }

PROTECTED=(
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
  lifeos-ha-issue-queue-bridge.service
)

for u in "${PROTECTED[@]}"; do
  before=$(systemctl is-active "$u" 2>/dev/null || true)
  [[ "$before" == active ]] || { echo "ERROR=protected_not_active:$u:$before"; exit 1; }
  echo "PROTECTED_BEFORE=$u:$before"
done

mapfile -t FAILED < <(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | sed '/^$/d')

allowed_unit() {
  case "$1" in
    lifeos-ansible-*-proof-*.service|lifeos-root-broker@*.service|lifeos-pi-control.service) return 0 ;;
    *) return 1 ;;
  esac
}

unexpected=()
for u in "${FAILED[@]}"; do
  allowed_unit "$u" || unexpected+=("$u")
done
if ((${#unexpected[@]})); then
  printf 'ERROR=unexpected_failed_unit:%s\n' "${unexpected[@]}"
  exit 1
fi

echo "FAILED_BEFORE=${#FAILED[@]}"

# Old two-repository relay is explicitly superseded by the canonical GitHub runner model.
# Disable both timer and service so native systemd cannot recreate a stale failure later.
if systemctl cat lifeos-pi-control.service >/dev/null 2>&1 || systemctl cat lifeos-pi-control.timer >/dev/null 2>&1; then
  systemctl disable --now lifeos-pi-control.timer lifeos-pi-control.service >/dev/null 2>&1 || true
  echo 'LIFEOS_PI_CONTROL=DISABLED_SUPERSEDED_TIMER_AND_SERVICE_PRESERVED'
else
  echo 'LIFEOS_PI_CONTROL=ABSENT'
fi

# Native systemd operation: clear only allow-listed historical failure state.
for u in "${FAILED[@]}"; do
  systemctl reset-failed "$u" || true
  echo "RESET_FAILED=$u"
done

mapfile -t AFTER < <(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | sed '/^$/d')
if ((${#AFTER[@]})); then
  printf 'ERROR=failed_unit_remains:%s\n' "${AFTER[@]}"
  exit 1
fi

for u in "${PROTECTED[@]}"; do
  after=$(systemctl is-active "$u" 2>/dev/null || true)
  [[ "$after" == active ]] || { echo "ERROR=protected_changed:$u:$after"; exit 1; }
  echo "PROTECTED_AFTER=$u:$after"
done

timer_state=$(systemctl is-enabled lifeos-pi-control.timer 2>/dev/null || true)
[[ "$timer_state" != enabled ]] || { echo 'ERROR=pi_control_timer_still_enabled'; exit 1; }

docker ps --format '{{.Names}} {{.Status}}' | grep -q '^homeassistant .*Up ' || { echo 'ERROR=homeassistant_not_running'; exit 1; }
docker ps --format '{{.Names}} {{.Status}}' | grep -q '^uptime-kuma .*Up ' || { echo 'ERROR=uptime_kuma_not_running'; exit 1; }
docker ps --format '{{.Names}} {{.Status}}' | grep -q 'semaphore' || { echo 'ERROR=semaphore_not_running'; exit 1; }

echo 'RESULT=PASS'
echo 'CAPABILITY_STAGE3_SYSTEMD_CLEANUP=PASS'
echo 'FAILED_SYSTEMD_UNITS=0'
echo 'LIFEOS_PI_CONTROL_TIMER_ENABLED=NO'
echo 'CUSTOM_SUPERVISOR_ADDED=NO'
echo 'OTS_MECHANISM=systemd_disable_and_reset_failed'
echo 'ROLLBACK=systemctl enable --now lifeos-pi-control.timer only if old relay architecture is intentionally restored'
