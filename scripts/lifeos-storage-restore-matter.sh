#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 0 ]] || exit 64
cd /home/joshan/lifeos-platform
exec lifeos-secret exec homeassistant.long_lived_access_token HA_TOKEN python3 -m governor.matter_storage_recovery
