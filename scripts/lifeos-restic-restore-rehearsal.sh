#!/usr/bin/env bash
set -Eeuo pipefail

STATE_DIR="${HOME}/.local/state/lifeos/restore-rehearsal"
mkdir -p "$STATE_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo 'RESTORE_REHEARSAL=START'
command -v restic >/dev/null || { echo 'RESTORE_REHEARSAL=BLOCKED reason=restic_missing'; exit 2; }

# Reuse the existing backup service's environment/credentials without printing them.
svc=lifeos-restic-backup.service
load_state="$(systemctl show "$svc" -p LoadState --value)"
[[ "$load_state" == loaded ]] || { echo 'RESTORE_REHEARSAL=BLOCKED reason=backup_service_missing'; exit 2; }

# systemd-run executes the read-only repository operations with the same environment files
# and credentials declared by the existing backup service. We never echo secret values.
mapfile -t envfiles < <(systemctl show "$svc" -p EnvironmentFiles --value | grep -oE '/[^ ;]+' || true)
args=(systemd-run --quiet --wait --pipe --collect --property=Type=oneshot)
for f in "${envfiles[@]}"; do args+=(--property="EnvironmentFile=$f"); done

latest="$(${args[@]} restic snapshots --latest 1 --json)"
python3 - "$latest" <<'PY'
import json,sys
x=json.loads(sys.argv[1])
if not x: raise SystemExit('no snapshots')
s=x[0]
print('SNAPSHOT_PRESENT=YES')
print('SNAPSHOT_TIME='+str(s.get('time','')))
print('SNAPSHOT_HOST='+str(s.get('hostname','')))
print('SNAPSHOT_PATH_COUNT='+str(len(s.get('paths') or [])))
PY

# Restic's repository-integrity check is non-mutating and proves repository/index/data readability.
${args[@]} restic check --read-data-subset=1/100 >/dev/null
echo 'RESTIC_CHECK=PASS'

# Prove an actual restore path without overwriting production: restore latest into an isolated temp target.
${args[@]} restic restore latest --target "$TMP/restore" >/dev/null
count="$(find "$TMP/restore" -type f 2>/dev/null | wc -l)"
[[ "$count" -gt 0 ]] || { echo 'RESTORE_REHEARSAL=FAIL reason=no_files_restored'; exit 1; }
echo "RESTORED_FILE_COUNT=$count"

python3 - "$STATE_DIR" "$count" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); count=int(sys.argv[2])
r={'schema_version':1,'timestamp':datetime.now(timezone.utc).isoformat(),'result':'PASS','repository_check':'PASS','actual_restore':'PASS','restored_file_count':count,'production_overwrite':False,'secrets_emitted':False}
fd,tmp=tempfile.mkstemp(prefix='.restore-rehearsal-',dir=p)
os.close(fd); Path(tmp).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); os.replace(tmp,p/'latest.json')
PY

echo 'PRODUCTION_OVERWRITE=NO'
echo 'SECRETS_EMITTED=NO'
echo 'RESTORE_REHEARSAL=PASS'
