#!/usr/bin/env bash
# Fixed config-only branch of the existing Restic restore gateway.
set -Eeuo pipefail
[[ $# -eq 0 && $EUID -eq 0 ]] || exit 64
cd /home/joshan/lifeos-platform
exec /usr/bin/timeout 75s /usr/bin/env -i PATH=/usr/bin:/bin \
    /usr/bin/python3 -B -m governor.adguard_restic_probe
