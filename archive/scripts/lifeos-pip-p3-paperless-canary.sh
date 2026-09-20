#!/usr/bin/env bash
set -Eeuo pipefail
container="${LIFEOS_PAPERLESS_CONTAINER:-paperless-paperless-1}"
repo="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
work="$(mktemp -d)"
trap 'rm -rf "$work"; docker exec "$container" rm -f /tmp/lifeos-pip-p2-lib.py /tmp/lifeos-pip-p3-canary.py >/dev/null 2>&1 || true' EXIT

docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true || { echo PAPERLESS_RUNTIME=UNAVAILABLE; echo RESULT=BLOCKED; exit 2; }

docker cp "$repo/scripts/lifeos-pip-p2-paperless-shadow.py" "$container:/tmp/lifeos-pip-p2-lib.py"
docker cp "$repo/scripts/lifeos-pip-p3-paperless-canary.py" "$container:/tmp/lifeos-pip-p3-canary.py"
docker exec -i "$container" python3 manage.py shell < "$repo/scripts/lifeos-pip-p3-paperless-canary.py" | tee "$work/result.txt"

grep -qx 'P3_SAFE_DOCUMENT_TYPE_RULES=2' "$work/result.txt"
grep -qx 'P3_SAFE_TAG_RULES=2' "$work/result.txt"
grep -qx 'P3_MATCHER_ROLLBACK=PASS' "$work/result.txt"
grep -qx 'P3_DOCUMENT_METADATA_MUTATION=NONE' "$work/result.txt"
grep -qx 'P3_NEW_TAXONOMY=NONE' "$work/result.txt"
grep -qx 'P3_TOWER_AI_USED=NO' "$work/result.txt"
grep -qx 'P3_PRIVATE_FIELDS_EMITTED=NONE' "$work/result.txt"
grep -qx 'P3_REVIEW_CANDIDATES_MUTATED=NO' "$work/result.txt"
grep -qx 'P3_CANARY=PASS' "$work/result.txt"
grep -qx 'RESULT=PASS' "$work/result.txt"
echo P3_WRAPPER=PASS
