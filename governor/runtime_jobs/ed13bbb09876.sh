#!/usr/bin/env bash
set -euo pipefail

readonly HEALTH_URL="http://127.0.0.1:8790/health"

health_json="$(timeout 10s curl --fail --silent --show-error \
  --connect-timeout 3 \
  --max-time 5 \
  "$HEALTH_URL")"

python3 -c '
import json
import sys

health = json.load(sys.stdin)
expected = {
    "service": "lifeos-autonomous-agent",
    "status": "ok",
    "runtime_controller": "pi5",
    "git_controller": "pi5",
}
for field, wanted in expected.items():
    actual = health.get(field)
    if actual != wanted:
        raise SystemExit(
            f"FAIL: health field {field!r} was {actual!r}, expected {wanted!r}"
        )
' <<<"$health_json"

printf '%s\n' 'RUNTIME_LOOP_SMOKE=PASS'
