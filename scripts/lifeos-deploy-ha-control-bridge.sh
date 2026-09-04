#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
# Refresh the root-owned allow-listed gateway from the canonical repository before
# executing the already-proven HA bridge/tower deployment. The historical deploy
# implementation can recreate legacy dashboard state, so always finish by applying
# the repository-native canonical LifeOS dashboard and verifying zero drift.
bash "$PLATFORM/scripts/lifeos-install-github-runner-gateway.sh"
bash "$PLATFORM/scripts/lifeos-deploy-ha-control-bridge-impl.sh"
python3 "$PLATFORM/homeassistant/deploy-lifeos-dashboard.py"
python3 "$PLATFORM/homeassistant/verify-lifeos-dashboard.py"
echo 'CANONICAL_LIFEOS_DASHBOARD=PASS'
