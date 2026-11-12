#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# -eq 0 ]] || exit 64
ulimit -v 262144
exec /usr/bin/timeout -k 5s 100s /usr/bin/ionice -c3 /usr/bin/nice -n 15 \
  /usr/bin/python3 -E -s -B -m governor.storage_root_allocation
