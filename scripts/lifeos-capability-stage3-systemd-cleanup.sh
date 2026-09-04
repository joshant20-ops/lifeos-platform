#!/usr/bin/env bash
set -Eeuo pipefail

# Capability Stage 3: native systemd cleanup only.
# No custom supervisor is introduced. Historical transient failed units are reset;
# the superseded lifeos-pi-control service is disabled/stopped but its unit file is
# preserved for rollback. Protected permanent control-plane units are never stopped.

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
if systemctl cat lifeos-pi-control.service >/dev/null 2>&1; then
  systemctl disable --now lifeos-pi-control.service >/dev/null 2>&1 || true
  echo 'LIFEOS_PI_CONTROL=DISABLED_SUPERSEDED_UNIT_PRESERVED'
else
  echo 'LIFEOS_PI_CONTROL=ABSENT'
fi

# Native systemd operation: clear only allow-listed historical failure state.
for u in "${FAILED[@]}"; do
  systemctl reset-failed "$u" || true
  echo "RESET_FAILED=$u"
done

# Re-evaluate and fail closed if anything remains failed.
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

# Current OTS/control runtime must still be healthy.
docker ps --format '{{.Names}} {{.Status}}' | grep -q '^homeassistant .*Up ' || { echo 'ERROR=homeassistant_not_running'; exit 1; }
docker ps --format '{{.Names}} {{.Status}}' | grep -q '^uptime-kuma .*Up ' || { echo 'ERROR=uptime_kuma_not_running'; exit 1; }
docker ps --format '{{.Names}} {{.Status}}' | grep -q 'semaphore' || { echo 'ERROR=semaphore_not_running'; exit 1; }

echo 'RESULT=PASS'
echo 'CAPABILITY_STAGE3_SYSTEMD_CLEANUP=PASS'
echo 'FAILED_SYSTEMD_UNITS=0'
echo 'CUSTOM_SUPERVISOR_ADDED=NO'
echo 'OTS_MECHANISM=systemd_reset_failed'
echo 'ROLLBACK=systemctl enable --now lifeos-pi-control.service only if old relay architecture is intentionally restored'
