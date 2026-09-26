#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
DISCOVERY="$PLATFORM/homeassistant/discover-house-status-entities.py"
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'HOUSE_STATUS_DISCOVERY=FAIL'; echo 'ERROR=must_run_as_root'; exit 1; }
[[ -f "$DISCOVERY" && ! -L "$DISCOVERY" ]] || { echo 'HOUSE_STATUS_DISCOVERY=FAIL'; echo 'ERROR=discovery_script_missing'; exit 1; }
python3 -m py_compile "$DISCOVERY"
echo 'HOUSE_STATUS_DISCOVERY=START'
python3 "$DISCOVERY"
echo 'HOUSE_STATUS_DISCOVERY=PASS'
