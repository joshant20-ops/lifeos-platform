#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
# Refresh the root-owned allow-listed gateway from the canonical repository before
# executing the already-proven HA deployment implementation. This keeps the runner
# privilege boundary current without granting arbitrary sudo.
bash "$PLATFORM/scripts/lifeos-install-github-runner-gateway.sh"
exec bash "$PLATFORM/scripts/lifeos-deploy-ha-control-bridge-impl.sh"
