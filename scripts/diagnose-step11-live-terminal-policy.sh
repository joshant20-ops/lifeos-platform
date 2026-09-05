#!/usr/bin/env bash
set -Eeuo pipefail

REPO=/home/joshan/lifeos-platform
LIVE=/usr/local/libexec/job_records.py
SOURCE="$REPO/governor/job_records.py"

fail(){ echo "FINAL_STATUS=FAIL"; echo "FAIL_REASON=$1"; exit 1; }

[[ -d "$REPO/.git" ]] || fail repo_missing
[[ -f "$SOURCE" ]] || fail source_missing
[[ -f "$LIVE" ]] || fail live_module_missing

HEAD=$(git -C "$REPO" rev-parse HEAD)
ORIGIN=$(git -C "$REPO" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || fail repo_not_at_origin_main

SRC_SHA=$(sha256sum "$SOURCE" | awk '{print $1}')
LIVE_SHA=$(sha256sum "$LIVE" | awk '{print $1}')

echo "SOURCE_COMMIT=$HEAD"
echo "SOURCE_SHA256=$SRC_SHA"
echo "LIVE_SHA256=$LIVE_SHA"

python3 - "$LIVE" <<'PY' || fail live_module_contract_invalid
import importlib.util,json,sys
p=sys.argv[1]
spec=importlib.util.spec_from_file_location('lifeos_job_records_live',p)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
base={'id':'probe','request':'probe','privacy':'normal','iterations':[]}
cases=[
 ({**base,'status':'PASS','stage':'complete'},'PASS',False),
 ({**base,'status':'BLOCKED','stage':'blocked','blocked_reason':'external dependency'},'BLOCKED',False),
 ({**base,'status':'BLOCKED','stage':'blocked_repeated_failure','blocked_reason':'repeated deterministic failure detected (3 occurrences)','repeated_failure_count':3,'last_failure_signature':'abc'},'REPEATED_FAILURE',False),
 ({**base,'status':'BLOCKED','stage':'blocked','blocked_reason':'maximum iterations reached'},'ITERATION_LIMIT',False),
 ({**base,'status':'RUNNING','stage':'builder'},'NON_TERMINAL',True),
]
for job,kind,retry in cases:
    rec=mod.make_record(job)
    term=rec.get('terminal_outcome') or {}
    assert term.get('kind')==kind,(kind,term)
    assert term.get('retry_allowed') is retry,(kind,term)
print('LIVE_TERMINAL_CONTRACT=PASS')
PY

if [[ "$SRC_SHA" != "$LIVE_SHA" ]]; then
  echo "LIVE_MODULE_SYNC=STALE"
  echo "FINAL_STATUS=BLOCKED"
  echo "NEXT_REQUIRED=bounded_job_records_module_deployment"
  exit 20
fi

echo "LIVE_MODULE_SYNC=PASS"
echo "FINAL_STATUS=PASS"
echo "NEXT_REQUIRED=step11_live_complete"
