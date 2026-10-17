#!/usr/bin/env bash
# Read-only inspection of fixed historical audit evidence that mentions stale-copy paths.
# This operation never changes or removes candidate data or evidence.
set -Eeuo pipefail

EXPECTED_DOCKER_FLEET_SHA256=32f07a333acba53c11f85531f031bea9542f18ac4c681034227759679e285190
EXPECTED_GRAFANA_EVIDENCE_SHA256=1b920eabd8135ae6247ddd374600d645d9b4360125d70e9b40d58d7066fabeee
FILES=(
  /home/joshan/automation/docker_fleet_auditor/evidence/docker_fleet_evidence_20260602_010106.json
  /home/joshan/automation/grafana_auditor/evidence/grafana_data_link_evidence_v3_20260602_005737.json
)

echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "OPERATION=storage-inspect-backup-evidence"
for i in "${!FILES[@]}"; do
  path="${FILES[$i]}"
  [[ -f "$path" && ! -L "$path" ]] || { echo "RESULT=FAIL"; echo "ERROR=evidence_missing_or_symlink:$path"; exit 1; }
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$i" == 0 ]]; then
    [[ "$actual" == "$EXPECTED_DOCKER_FLEET_SHA256" ]] || { echo "RESULT=FAIL"; echo "ERROR=docker_fleet_evidence_hash_mismatch:$actual"; exit 1; }
    echo "DOCKER_FLEET_EVIDENCE_HASH_CHECK=PASS"
  else
    [[ "$actual" == "$EXPECTED_GRAFANA_EVIDENCE_SHA256" ]] || { echo "RESULT=FAIL"; echo "ERROR=grafana_evidence_hash_mismatch:$actual"; exit 1; }
    echo "GRAFANA_EVIDENCE_HASH_CHECK=PASS"
  fi
  echo "EVIDENCE_FILE=$path"
  echo "EVIDENCE_SHA256=$actual"
  stat -c 'EVIDENCE_STAT=size:%s owner:%U:%G mode:%a mtime:%y' "$path"
  python3 - "$path" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    data = json.load(f)
print('EVIDENCE_JSON_TOP_LEVEL_TYPE=' + type(data).__name__)
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
done
echo "RESULT=PASS"
