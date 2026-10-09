#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
exec /usr/bin/python3 "$PLATFORM/scripts/lifeos-configure-ai-dns.py"
