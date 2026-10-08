#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# -eq 2 && "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9]{1,20}$ ]] || {
  echo "TOWER_WOL_CAPTURE_REQUEST=REJECTED"
  exit 64
}
cd /home/joshan/lifeos-platform
exec python3 scripts/lifeos-tower-wol-packet-diagnostic.py --mode capture --expected-fingerprint "$1" --run-id "$2"
