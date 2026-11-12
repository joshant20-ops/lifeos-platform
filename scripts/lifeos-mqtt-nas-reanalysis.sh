#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 0 && $EUID -eq 0 ]] || exit 64
cd /home/joshan/lifeos-platform
exec /usr/bin/timeout -k 10s 2940s /usr/bin/ionice -c2 -n7 /usr/bin/nice -n 15 \
    /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/bin /usr/bin/python3 -I -B -c \
    'import sys; sys.path.insert(0, "/home/joshan/lifeos-platform"); from governor.mqtt_nas_reanalysis import main; raise SystemExit(main())'
