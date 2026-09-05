#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
HA_ROOT=/opt/stacks/homeassistant/config
UNIT_DIR=/etc/systemd/system

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
cd "$PLATFORM"

head_sha=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
origin_sha=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
status=$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)
[[ "$head_sha" == "$origin_sha" && -z "$status" ]] || { echo 'ERROR=repository_not_clean_origin_main'; exit 1; }

echo 'WAVE_A_DEPLOY_PREFLIGHT=PASS'

# Unit tests before any live mutation.
runuser -u joshan -- /usr/bin/python3 -m unittest tests.test_wave_a_energy_attention

echo 'WAVE_A_PROJECTOR_TESTS=PASS'

# The recurring service deliberately runs unprivileged. Prove its two required write/read boundaries.
[[ -d "$HA_ROOT" ]] || { echo 'ERROR=ha_config_root_missing'; exit 1; }
runuser -u joshan -- test -w "$HA_ROOT" || { echo 'ERROR=ha_config_not_writable_by_joshan'; exit 1; }
runuser -u joshan -- test -r /var/run/docker.sock || { echo 'ERROR=docker_socket_not_readable_by_joshan'; exit 1; }

echo 'WAVE_A_UNPRIVILEGED_RUNTIME_BOUNDARY=PASS'

install -o joshan -g joshan -m 0755 \
  "$PLATFORM/homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_energy_attention_sensor.py" \
  "$HA_ROOT/scripts/lifeos_energy_attention_sensor.py"
install -o joshan -g joshan -m 0644 \
  "$PLATFORM/homelab/live/opt/stacks/homeassistant/config/packages/lifeos_energy_attention.yaml" \
  "$HA_ROOT/packages/lifeos_energy_attention.yaml"
install -o joshan -g joshan -m 0644 \
  "$PLATFORM/homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml" \
  "$HA_ROOT/packages/lifeos_attention.yaml"

# Generate the first projection before Home Assistant validates the package.
runuser -u joshan -- /usr/bin/python3 "$PLATFORM/scripts/run-wave-a-energy-attention.py"

echo 'WAVE_A_INITIAL_PROJECTION=PASS'

# Validate HA configuration before restart.
docker exec homeassistant python -m homeassistant --script check_config -c /config

echo 'WAVE_A_HA_CONFIG_CHECK=PASS'

install -o root -g root -m 0644 \
  "$PLATFORM/homelab/live/etc/systemd/system/lifeos-energy-opportunity-attention.service" \
  "$UNIT_DIR/lifeos-energy-opportunity-attention.service"
install -o root -g root -m 0644 \
  "$PLATFORM/homelab/live/etc/systemd/system/lifeos-energy-opportunity-attention.timer" \
  "$UNIT_DIR/lifeos-energy-opportunity-attention.timer"
systemctl daemon-reload
systemctl enable --now lifeos-energy-opportunity-attention.timer
systemctl start lifeos-energy-opportunity-attention.service
[[ "$(systemctl is-enabled lifeos-energy-opportunity-attention.timer)" == enabled ]]
[[ "$(systemctl is-active lifeos-energy-opportunity-attention.timer)" == active ]]
[[ "$(systemctl show -p Result --value lifeos-energy-opportunity-attention.service)" == success ]]

echo 'WAVE_A_LOCAL_SCHEDULER=PASS'

# Restart only after all local checks pass, then prove HA healthy again.
docker restart homeassistant >/dev/null
for _ in $(seq 1 90); do
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
  [[ "$health" == healthy || "$health" == running ]] && break
  sleep 2
done
health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
[[ "$health" == healthy || "$health" == running ]] || { echo "ERROR=homeassistant_health:$health"; exit 1; }

echo 'WAVE_A_HOME_ASSISTANT=PASS'
echo 'WAVE_A_ENERGY_ATTENTION_DEPLOY=PASS'
