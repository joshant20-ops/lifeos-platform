#!/usr/bin/env bash
set -Eeuo pipefail
STATE_DIR="${HOME}/.local/state/lifeos/restore-rehearsal"; mkdir -p "$STATE_DIR"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo 'RESTORE_REHEARSAL=START'
command -v restic >/dev/null || { echo 'RESTORE_REHEARSAL=BLOCKED reason=restic_missing'; exit 2; }
svc=lifeos-restic-backup.service
[[ "$(systemctl show "$svc" -p LoadState --value)" == loaded ]] || { echo 'RESTORE_REHEARSAL=BLOCKED reason=backup_service_missing'; exit 2; }
# Import Environment= values in-memory. Never print them.
while IFS= read -r -d '' assignment; do export "$assignment"; done < <(python3 - "$svc" <<'PY'
import os,shlex,subprocess,sys
raw=subprocess.check_output(['systemctl','show',sys.argv[1],'-p','Environment','--value'],text=True)
for item in shlex.split(raw):
    if '=' in item: os.write(1,item.encode()+b'\0')
PY
)
# Import any EnvironmentFile= entries declared by the actual installed unit.
while IFS= read -r f; do
  [[ -r "$f" ]] || continue
  set -a
  # shellcheck disable=SC1090
  source "$f"
  set +a
done < <(systemctl cat "$svc" | sed -nE 's/^[[:space:]]*EnvironmentFile=-?([^[:space:]]+).*/\1/p')
# Some backup units place the restic environment directly on ExecStart via env(1).
execstart="$(systemctl show "$svc" -p ExecStart --value)"
while IFS= read -r -d '' assignment; do export "$assignment"; done < <(python3 - "$execstart" <<'PY'
import os,re,shlex,sys
raw=sys.argv[1]
for tok in shlex.split(raw):
    if re.match(r'^(RESTIC_[A-Z0-9_]+|AWS_[A-Z0-9_]+|B2_[A-Z0-9_]+|AZURE_[A-Z0-9_]+)=',tok): os.write(1,tok.encode()+b'\0')
PY
)
: "${RESTIC_REPOSITORY:?backup service contract does not expose RESTIC_REPOSITORY}"
latest="$(restic snapshots --latest 1 --json)"
python3 - "$latest" <<'PY'
import json,sys
x=json.loads(sys.argv[1]); assert x, 'no snapshots'; s=x[0]
print('SNAPSHOT_PRESENT=YES'); print('SNAPSHOT_TIME='+str(s.get('time',''))); print('SNAPSHOT_HOST='+str(s.get('hostname',''))); print('SNAPSHOT_PATH_COUNT='+str(len(s.get('paths') or [])))
PY
restic check --read-data-subset=1/100 >/dev/null
echo 'RESTIC_CHECK=PASS'
restic restore latest --target "$TMP/restore" >/dev/null
count="$(find "$TMP/restore" -type f 2>/dev/null | wc -l)"
[[ "$count" -gt 0 ]] || { echo 'RESTORE_REHEARSAL=FAIL reason=no_files_restored'; exit 1; }
echo "RESTORED_FILE_COUNT=$count"
python3 - "$STATE_DIR" "$count" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
p=Path(sys.argv[1]); count=int(sys.argv[2]); r={'schema_version':1,'timestamp':datetime.now(timezone.utc).isoformat(),'result':'PASS','repository_check':'PASS','actual_restore':'PASS','restored_file_count':count,'production_overwrite':False,'secrets_emitted':False}
fd,tmp=tempfile.mkstemp(prefix='.restore-rehearsal-',dir=p); os.close(fd); Path(tmp).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); os.replace(tmp,p/'latest.json')
PY
echo 'PRODUCTION_OVERWRITE=NO'; echo 'SECRETS_EMITTED=NO'; echo 'RESTORE_REHEARSAL=PASS'
