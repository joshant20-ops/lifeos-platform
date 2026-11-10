#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 0 && $EUID -eq 0 ]] || exit 64
cd /home/joshan/lifeos-platform
exec /usr/bin/timeout 150s /usr/bin/ionice -c3 /usr/bin/nice -n 15 \
    /usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/python3 -I -B \
    /home/joshan/lifeos-platform/governor/adguard_restic_tree_probe.py
