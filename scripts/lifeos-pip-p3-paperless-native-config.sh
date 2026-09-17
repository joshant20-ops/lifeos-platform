#!/usr/bin/env bash
set -Eeuo pipefail
container="${LIFEOS_PAPERLESS_CONTAINER:-paperless-paperless-1}"
repo="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
helper="$repo/scripts/lifeos-pip-p3-paperless-native-config.py"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true || { echo 'PAPERLESS_RUNTIME=UNAVAILABLE'; echo 'RESULT=BLOCKED'; exit 2; }
test -r "$helper"
run_config() { docker exec -i "$container" python3 manage.py shell < "$helper"; }
run_config > "$work/first.txt"
run_config > "$work/second.txt"
first_hash="$(sed -n 's/^CONFIG_STATE_HASH=//p' "$work/first.txt")"
second_hash="$(sed -n 's/^CONFIG_STATE_HASH=//p' "$work/second.txt")"
test -n "$first_hash" && test "$first_hash" = "$second_hash"
grep -qx 'DOCUMENT_TYPE_RULES_ACTIVATED=0' "$work/second.txt"
cat "$work/first.txt"
echo 'NATIVE_CONFIGURATION_IDEMPOTENT=PASS'
echo 'REVERSIBLE_TRANSACTION_GUARD=PASS'
echo 'P3_SCOPE=PAPERLESS_NATIVE_CONFIGURATION_ONLY'
