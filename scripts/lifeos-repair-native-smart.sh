#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 0 ]] || exit 64
cd /home/joshan/lifeos-platform
exec python3 -m governor.smart_native_repair
