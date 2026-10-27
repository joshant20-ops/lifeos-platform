#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 0 ]] || exit 64
cd /home/joshan/lifeos-platform
exec python3 -m governor.storage_boot_acceptance prepare
