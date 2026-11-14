#!/usr/bin/env bash
set -Eeuo pipefail

python3 /home/joshan/lifeos-platform/governor/paperless_runtime_diagnostic.py
# Fixed read-only API inventory; no response bodies or exception text emitted.
timeout --kill-after=2s 40s python3 /home/joshan/lifeos-platform/governor/paperless_capability_audit.py || echo 'PAPERLESS_CAPABILITY_RESULT=UNAVAILABLE'
