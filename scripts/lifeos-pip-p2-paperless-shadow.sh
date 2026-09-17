#!/usr/bin/env bash
set -Eeuo pipefail

container="${LIFEOS_PAPERLESS_CONTAINER:-paperless-paperless-1}"
repo="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
helper="$repo/scripts/lifeos-pip-p2-paperless-shadow.py"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true || {
  echo 'PAPERLESS_RUNTIME=UNAVAILABLE'; echo 'RESULT=BLOCKED'; exit 2;
}
test -r "$helper"

run_shadow() {
  docker exec -i "$container" python3 manage.py shell < "$helper"
}

run_shadow > "$work/first.txt"
run_shadow > "$work/second.txt"
cmp -s "$work/first.txt" "$work/second.txt" || {
  echo 'IDEMPOTENT_IDENTICAL_RERUN=FAIL'
  echo 'RESULT=FAIL'
  exit 1
}
cat "$work/first.txt"
echo 'IDEMPOTENT_IDENTICAL_RERUN=PASS'
echo 'SHADOW_EVALUATOR_REUSABLE=PASS'
