#!/usr/bin/env bash
set -Eeuo pipefail
cd /home/joshan/lifeos-platform
exec python3 scripts/lifeos-tower-wol-packet-diagnostic.py --mode inspect --expected-fingerprint "" --run-id ""
