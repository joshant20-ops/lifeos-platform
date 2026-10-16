#!/usr/bin/env bash
# Read-only inspection of the exact historical evidence file blocking the
# stale-copy preflight. No candidate data is modified or copied.
set -Eeuo pipefail

EVIDENCE=/home/joshan/automation/docker_fleet_auditor/evidence/docker_fleet_evidence_20260602_010106.json
[[ -f "$EVIDENCE" && ! -L "$EVIDENCE" ]] || { echo "RESULT=FAIL"; echo "ERROR=evidence_missing_or_symlink"; exit 1; }

echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "OPERATION=storage-inspect-backup-evidence"
echo "EVIDENCE_FILE=$EVIDENCE"
stat -c 'EVIDENCE_STAT=size:%s owner:%U:%G mode:%a mtime:%y' "$EVIDENCE"
sha256sum "$EVIDENCE" | sed 's#  .*#  [fixed evidence file]#'

python3 - "$EVIDENCE" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    data = json.load(f)
print('EVIDENCE_JSON_TOP_LEVEL_TYPE=' + type(data).__name__)
if isinstance(data, dict):
    print('EVIDENCE_JSON_TOP_LEVEL_KEYS=' + ','.join(sorted(str(k) for k in data.keys())))
else:
    print('EVIDENCE_JSON_TOP_LEVEL_KEYS=NONE')
needles = (
    '/mnt/docker-data/pre_day7_backup',
    '/mnt/docker-data/host-data/opt-stacks',
    'pre_day7_backup',
    'host-data/opt-stacks',
)
matches = []
def visit(value, keypath='$'):
    if isinstance(value, dict):
        for key, child in value.items():
            visit(child, keypath + '.' + str(key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            visit(child, f'{keypath}[{i}]')
    elif isinstance(value, str):
        for needle in needles:
            if needle in value:
                matches.append((keypath, value))
                break
visit(data)
for keypath, value in matches:
    print('EVIDENCE_REFERENCE_PATH=' + keypath)
    print('EVIDENCE_REFERENCE_VALUE=' + value)
print(f'EVIDENCE_REFERENCE_COUNT={len(matches)}')
PY

echo "RESULT=PASS"
