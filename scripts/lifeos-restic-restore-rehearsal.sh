#!/usr/bin/env bash
set -Eeuo pipefail
STATE_DIR="${HOME}/.local/state/lifeos/restore-rehearsal"; mkdir -p "$STATE_DIR"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo 'RESTORE_REHEARSAL=START'
command -v restic >/dev/null || { echo 'RESTORE_REHEARSAL=BLOCKED reason=restic_missing'; exit 2; }
svc=lifeos-restic-backup.service
mapfile -t load_state < <(systemctl show "$svc" -p LoadState --value)
[[ "${load_state[0]:-}" == loaded ]] || { echo 'RESTORE_REHEARSAL=BLOCKED reason=backup_service_missing'; exit 2; }
mapfile -d '' -t restic_env < <(python3 - "$svc" <<'PY'
import os,re,shlex,subprocess,sys
allow=re.compile(r'^(RESTIC_[A-Z0-9_]+|AWS_[A-Z0-9_]+|B2_[A-Z0-9_]+|AZURE_[A-Z0-9_]+)=')
svc=sys.argv[1]; items=shlex.split(subprocess.check_output(['systemctl','show',svc,'-p','Environment','--value'],text=True)); unit=subprocess.check_output(['systemctl','cat',svc],text=True)
for rawpath in re.findall(r'^\s*EnvironmentFile=-?([^\s]+)',unit,re.M):
    path=rawpath.strip('"\'')
    try: fh=open(path)
    except OSError: continue
    with fh:
        for rawline in fh:
            line=rawline.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('export '): line=line[7:].lstrip()
            try: items.extend(shlex.split(line,comments=True,posix=True))
            except ValueError: continue
for item in items:
    if allow.match(item): os.write(1,item.encode()+b'\0')
PY
)
repo_found=0
for assignment in "${restic_env[@]}"; do [[ "$assignment" == RESTIC_REPOSITORY=* ]] && repo_found=1; done
[[ "$repo_found" -eq 1 ]] || { echo 'RESTORE_REHEARSAL=FAIL reason=repository_contract_missing'; exit 1; }
run_restic() { env "${restic_env[@]}" restic "$@"; }
run_restic snapshots --latest 1 --json >"$TMP/latest.json"
python3 - "$TMP/latest.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); assert x, 'no snapshots'; s=x[0]
print('SNAPSHOT_PRESENT=YES'); print('SNAPSHOT_TIME='+str(s.get('time',''))); print('SNAPSHOT_HOST='+str(s.get('hostname',''))); print('SNAPSHOT_PATH_COUNT='+str(len(s.get('paths') or [])))
PY
run_restic check --read-data-subset=1/100 >/dev/null
echo 'RESTIC_CHECK=PASS'
run_restic restore latest --target "$TMP/restore" >/dev/null
python3 - "$TMP/restore" "$STATE_DIR" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1]); p=Path(sys.argv[2]); count=sum(1 for f in root.rglob('*') if f.is_file())
if count <= 0: raise SystemExit('no files restored')
print(f'RESTORED_FILE_COUNT={count}')
r={'schema_version':1,'timestamp':datetime.now(timezone.utc).isoformat(),'result':'PASS','repository_check':'PASS','actual_restore':'PASS','restored_file_count':count,'production_overwrite':False,'secrets_emitted':False}
fd,tmp=tempfile.mkstemp(prefix='.restore-rehearsal-',dir=p); os.close(fd); Path(tmp).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n'); os.replace(tmp,p/'latest.json')
PY
echo 'PRODUCTION_OVERWRITE=NO'; echo 'SECRETS_EMITTED=NO'; echo 'RESTORE_REHEARSAL=PASS'
