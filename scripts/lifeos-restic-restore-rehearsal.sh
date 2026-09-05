#!/usr/bin/env bash
set -Eeuo pipefail
STATE_DIR="${HOME}/.local/state/lifeos/restore-rehearsal"; mkdir -p "$STATE_DIR"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo 'RESTORE_REHEARSAL=START'
svc=lifeos-restic-backup.service
systemctl show "$svc" -p LoadState --value >"$TMP/loadstate"
read -r loadstate <"$TMP/loadstate"
[[ "$loadstate" == loaded ]] || { echo 'RESTORE_REHEARSAL=BLOCKED reason=backup_service_missing'; exit 2; }
systemctl cat "$svc" >"$TMP/unit"
python3 - "$TMP/unit" "$TMP/env" <<'PY'
import json,re,shlex,sys
from pathlib import Path
unit=Path(sys.argv[1]).read_text(encoding='utf-8'); env={}
for rawpath in re.findall(r'^\s*EnvironmentFile=-?([^\s]+)',unit,re.M):
    path=Path(rawpath.strip('"\''))
    try: lines=path.read_text(encoding='utf-8').splitlines()
    except OSError: continue
    for raw in lines:
        line=raw.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('export '): line=line[7:].lstrip()
        try: parts=shlex.split(line,comments=True,posix=True)
        except ValueError: continue
        for item in parts:
            if re.match(r'^(RESTIC_[A-Z0-9_]+|AWS_[A-Z0-9_]+|B2_[A-Z0-9_]+|AZURE_[A-Z0-9_]+)=',item):
                k,v=item.split('=',1); env[k]=v
if 'RESTIC_REPOSITORY' not in env: raise SystemExit('repository contract missing')
Path(sys.argv[2]).write_text(json.dumps(env),encoding='utf-8')
PY
python3 - "$TMP/env" "$TMP/latest.json" <<'PY'
import json,os,subprocess,sys  # nosec B404
env=os.environ.copy(); env.update(json.load(open(sys.argv[1])))
p=subprocess.run(['/usr/bin/restic','snapshots','--latest','1','--json'],env=env,text=True,check=True,stdout=subprocess.PIPE)  # nosec B603
open(sys.argv[2],'w').write(p.stdout)
PY
python3 - "$TMP/latest.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1])); assert x; s=x[0]
print('SNAPSHOT_PRESENT=YES'); print('SNAPSHOT_TIME='+str(s.get('time',''))); print('SNAPSHOT_HOST='+str(s.get('hostname',''))); print('SNAPSHOT_PATH_COUNT='+str(len(s.get('paths') or [])))
PY
python3 - "$TMP/env" "$TMP/restore" <<'PY'
import json,os,subprocess,sys  # nosec B404
env=os.environ.copy(); env.update(json.load(open(sys.argv[1])))
subprocess.run(['/usr/bin/restic','check','--read-data-subset=1/100'],env=env,check=True,stdout=subprocess.DEVNULL)  # nosec B603
print('RESTIC_CHECK=PASS')
subprocess.run(['/usr/bin/restic','restore','latest','--target',sys.argv[2]],env=env,check=True,stdout=subprocess.DEVNULL)  # nosec B603
PY
python3 - "$TMP/restore" "$STATE_DIR" <<'PY'
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
root=Path(sys.argv[1]); p=Path(sys.argv[2]); count=sum(1 for f in root.rglob('*') if f.is_file()); assert count>0
print(f'RESTORED_FILE_COUNT={count}')
r={'schema_version':1,'timestamp':datetime.now(timezone.utc).isoformat(),'result':'PASS','repository_check':'PASS','actual_restore':'PASS','restored_file_count':count,'production_overwrite':False,'secrets_emitted':False}
fd,tmp=tempfile.mkstemp(prefix='.restore-rehearsal-',dir=p); os.close(fd); Path(tmp).write_text(json.dumps(r,indent=2)+'\n'); os.replace(tmp,p/'latest.json')
PY
echo 'PRODUCTION_OVERWRITE=NO'; echo 'SECRETS_EMITTED=NO'; echo 'RESTORE_REHEARSAL=PASS'
