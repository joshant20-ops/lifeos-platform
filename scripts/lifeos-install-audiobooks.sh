#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 0 ]] || { echo 'AUDIOBOOKS_ARGUMENTS=REJECTED'; exit 64; }
[[ $EUID -eq 0 ]] || { echo 'AUDIOBOOKS_ROOT=REQUIRED'; exit 1; }
exec /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 \
  /usr/bin/python3 -I /home/joshan/lifeos-platform/services/audiobookshelf/install.py
