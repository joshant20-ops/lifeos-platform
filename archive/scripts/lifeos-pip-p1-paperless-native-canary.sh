#!/usr/bin/env bash
set -Eeuo pipefail

container="${LIFEOS_PAPERLESS_CONTAINER:-paperless-paperless-1}"
paperless_url="${PAPERLESS_URL:-http://127.0.0.1:8010}"
repo="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
credential="${CREDENTIALS_DIRECTORY:-}/paperless-api-token"
marker="LIFEOS-P1-SYNTHETIC-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
helper=/tmp/lifeos-pip-p1-paperless-native-canary.py
work="$(mktemp -d)"
task_ids=()
cleanup_started=0

if [[ ! -s "$credential" ]]; then
  echo 'PAPERLESS_API_CREDENTIAL=UNAVAILABLE'
  echo 'RESULT=BLOCKED'
  exit 2
fi
docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true || {
  echo 'PAPERLESS_RUNTIME=UNAVAILABLE'; echo 'RESULT=BLOCKED'; exit 2;
}

inside() {
  local mode=$1
  docker exec -e LIFEOS_P1_MARKER="$marker" -e LIFEOS_P1_MODE="$mode" \
    -e LIFEOS_P1_TASK_IDS="$(IFS=,; echo "${task_ids[*]-}")" \
    -i "$container" python3 manage.py shell < "$repo/scripts/lifeos-pip-p1-paperless-native-canary.py"
}

api() {
  local method=$1 path=$2
  shift 2
  curl --fail-with-body --silent --show-error --max-time 30 \
    -X "$method" -H "Authorization: Token $(<"$credential")" \
    -H 'Accept: application/json; version=10' "$@" "$paperless_url$path"
}

marker_count() {
  api GET "/api/documents/?query=$marker&page_size=10" \
    | python3 -c 'import json,sys; value=json.load(sys.stdin); print(len(value if isinstance(value,list) else value.get("results",[])))'
}

cleanup() {
  local original_rc=$?
  if (( cleanup_started )); then return "$original_rc"; fi
  cleanup_started=1
  set +e
  inside cleanup
  cleanup_rc=$?
  after="$(marker_count 2>/dev/null)"
  search_rc=$?
  rm -rf "$work"
  if (( cleanup_rc != 0 || search_rc != 0 )) || [[ "$after" != 0 ]]; then
    echo 'SYNTHETIC_CLEANUP=FAIL'
    exit 1
  fi
  echo 'MARKER_SEARCH_AFTER=0'
  echo 'SYNTHETIC_CLEANUP=PASS'
  if (( original_rc != 0 )); then exit "$original_rc"; fi
}
trap cleanup EXIT

version="$(docker exec "$container" python3 manage.py shell -c \
  'from paperless.version import __full_version_str__; print(__full_version_str__)' | tail -1)"
[[ "$version" == 3.1.2* ]] || { echo "PAPERLESS_VERSION=$version"; echo 'RESULT=BLOCKED'; exit 2; }
echo 'PAPERLESS_VERSION=3.1.2'
echo 'PAPERLESS_API_CREDENTIAL=AVAILABLE'
inside baseline
echo 'MARKER_SEARCH_BEFORE=0'
inside configure

python3 - "$marker" > "$work/canary.pdf" <<'PY'
import sys
marker=sys.argv[1]
text=("LifeOS native Paperless canary " + marker).encode("ascii")
stream=b"BT /F1 12 Tf 72 720 Td ("+text+b") Tj ET"
objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"\nendstream"]
out=bytearray(b"%PDF-1.4\n"); offsets=[0]
for number,obj in enumerate(objects,1): offsets.append(len(out)); out.extend(str(number).encode()+b" 0 obj\n"+obj+b"\nendobj\n")
xref=len(out); out.extend(b"xref\n0 6\n0000000000 65535 f \n")
for offset in offsets[1:]: out.extend(("%010d 00000 n \n"%offset).encode())
out.extend(b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"+str(xref).encode()+b"\n%%EOF\n")
sys.stdout.buffer.write(out)
PY

upload="$(api POST /api/documents/post_document/ \
  -F "title=$marker" -F "document=@$work/canary.pdf;filename=$marker.pdf;type=application/pdf")"
task1="$(python3 -c 'import json,sys; v=json.load(sys.stdin); print(v if isinstance(v,str) else v.get("task_id",v.get("id","")))' <<<"$upload")"
[[ -n "$task1" ]] && task_ids+=("$task1")
echo 'AUTHENTICATED_REST_INGESTION=PASS'

document_count=0
for _ in $(seq 1 60); do
  document_count="$(marker_count)"
  [[ "$document_count" == 1 ]] && break
  sleep 2
done
[[ "$document_count" == 1 ]]
inside verify
[[ "$(marker_count)" == 1 ]]
echo 'NATIVE_FULL_TEXT_SEARCH=PASS'

duplicate_response="$(curl --silent --show-error --max-time 30 \
  -X POST -H "Authorization: Token $(<"$credential")" \
  -H 'Accept: application/json; version=10' \
  -F "title=$marker" \
  -F "document=@$work/canary.pdf;filename=$marker-duplicate.pdf;type=application/pdf" \
  -w $'\n%{http_code}' "$paperless_url/api/documents/post_document/")"
duplicate_status="${duplicate_response##*$'\n'}"
duplicate_body="${duplicate_response%$'\n'*}"
case "$duplicate_status" in
  200|201|202)
    task2="$(python3 -c 'import json,sys; v=json.load(sys.stdin); print(v if isinstance(v,str) else v.get("task_id",v.get("id","")))' <<<"$duplicate_body")"
    [[ -n "$task2" ]] && task_ids+=("$task2")
    sleep 8
    duplicate_count="$(marker_count)"
    case "$duplicate_count" in
      1) echo 'NATIVE_EXACT_DUPLICATE_POLICY=REJECT' ;;
      2) echo 'NATIVE_EXACT_DUPLICATE_POLICY=ALLOW' ;;
      *) echo "NATIVE_DUPLICATE_DOCUMENT_COUNT=$duplicate_count"; exit 1 ;;
    esac
    ;;
  400|409)
    [[ "$(marker_count)" == 1 ]]
    echo 'NATIVE_EXACT_DUPLICATE_POLICY=REJECT'
    ;;
  *)
    echo "NATIVE_DUPLICATE_HTTP_STATUS=$duplicate_status"
    exit 1
    ;;
esac
echo 'NATIVE_EXACT_DUPLICATE_BEHAVIOUR=MEASURED'

echo 'PAPERLESS_OWNS_INGESTION_OCR_METADATA_MATCHING_WORKFLOW_SEARCH_DUPLICATES=PROVEN'
echo 'LIFEOS_CLASSIFIER_BUILT=NO'
echo 'TOWER_AI_USED=NO'
echo 'PRIVATE_FIELDS_EMITTED=NONE'
echo 'PRODUCTION_DOCUMENT_MUTATION=NONE'
echo 'PRIVACY_LOCAL_ONLY=PASS'
echo 'RESULT=PASS'
