#!/usr/bin/env bash
set -Eeuo pipefail
cd /home/joshan/lifeos-platform
exec /usr/bin/timeout -k 20s 24m /usr/bin/ionice -c3 /usr/bin/nice -n 15 \
    /usr/bin/python3 -E -s -B -m governor.paperless_recovery_rehearsal
