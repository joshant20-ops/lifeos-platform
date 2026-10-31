#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 0 && $EUID -eq 0 ]] || exit 64
exec /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 \
 /usr/bin/python3 -I /home/joshan/lifeos-platform/services/audiobookshelf/backup.py
