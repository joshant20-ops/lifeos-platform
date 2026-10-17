#!/usr/bin/env bash
# Fixed read-only audit of Pi storage topology and persistent-data placement.
set -Eeuo pipefail

SSD=/mnt/docker-data
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "OPERATION=storage-audit-pi-state"
echo "EXPECTED_SSD_UUID=$EXPECTED_UUID"
echo "--- filesystem ---"
df -hT / "$SSD" /opt/stacks 2>&1
for p in "$SSD" /opt/stacks /home/joshan /home/joshan/lifeos-platform /home/joshan/automation /opt/actions-runner-lifeos /opt/actions-runner-lifeos/_work /var/mail/joshan /var/swap; do
  [[ -e "$p" ]] || continue
  echo "PATH=$p"
  findmnt -n -o SOURCE,FSTYPE,UUID,TARGET,OPTIONS -T "$p" || true
  stat -c 'STAT=dev:%d bytes:%s mode:%a owner:%U:%G' "$p" 2>/dev/null || true
  if [[ -d "$p" ]]; then du -sx --block-size=1 "$p" 2>/dev/null || true; fi
done

echo "--- fstab sanitized ---"
python3 - <<'PY'
from pathlib import Path
for raw in Path('/etc/fstab').read_text(errors='replace').splitlines():
    line=raw.strip()
    if not line or line.startswith('#'):
        continue
    cols=line.split()
    if len(cols) < 4:
        print('FSTAB_MALFORMED=' + line[:240])
        continue
    options=[]
    for item in cols[3].split(','):
        key=item.split('=',1)[0]
        options.append(key + ('=<redacted>' if key.lower() in {'password','passwd','credentials','username','user'} and '=' in item else ('='+item.split('=',1)[1] if '=' in item else '')))
    print('FSTAB=' + ' '.join(cols[:3]) + ' ' + ','.join(options))
PY

echo "--- docker ---"
docker info --format 'DOCKER_ROOT={{.DockerRootDir}}'
docker ps --format 'CONTAINER={{.Names}} STATUS={{.Status}}'
docker ps -a --format 'CONTAINER_ALL={{.Names}} STATUS={{.Status}}'
docker compose ls --all --format json 2>&1 | python3 -c '
import json,sys
raw=sys.stdin.read()
try:
    data=json.loads(raw)
except Exception:
    print("COMPOSE_PROJECTS_JSON_PARSE=FAILED")
    print("COMPOSE_PROJECTS_RAW=" + raw[:3000])
    raise SystemExit(0)
for project in data:
    print("COMPOSE_PROJECT=" + json.dumps({k:project.get(k) for k in ("Name","Status","ConfigFiles")}, sort_keys=True))
'
docker inspect $(docker ps -aq) | python3 -c '
import json,sys
items=json.load(sys.stdin)
for c in items:
    name=(c.get("Name") or "").lstrip("/")
    state=c.get("State") or {}
    health=((state.get("Health") or {}).get("Status") or "no-healthcheck")
    labels=c.get("Config",{}).get("Labels") or {}
    print(f"CONTAINER_DETAIL={name} state={state.get("Status")} health={health}")
    print("COMPOSE_METADATA=" + json.dumps({k:labels.get(k) for k in ("com.docker.compose.project","com.docker.compose.project.working_dir","com.docker.compose.project.config_files")},sort_keys=True))
    for m in c.get("Mounts",[]):
        print("CONTAINER_MOUNT=" + json.dumps({k:m.get(k) for k in ("Type","Name","Source","Destination","RW")},sort_keys=True))
' || { echo "DOCKER_INSPECT_AUDIT=FAIL"; exit 1; }

echo "--- systemd and timers ---"
systemctl --failed --no-legend --plain
systemctl list-units --type=service --state=running --no-legend --plain
systemctl list-timers --all --no-legend --plain
systemctl show docker.service containerd.service -p Id -p ActiveState -p SubState -p Requires -p Wants -p After -p FragmentPath -p ExecStart

echo "--- runner ---"
systemctl list-units --all --type=service --no-legend --plain | grep -Ei 'runner|actions' || true
ps -eo comm= | grep -Ei 'Runner|actions' || true

echo "--- canonical stack manifests ---"
find /opt/stacks -maxdepth 3 -type f \( -name docker-compose.yml -o -name compose.yml \) -print 2>/dev/null | sort
echo "--- data footprint ---"
du -x -d1 -h /opt/stacks /home/joshan /opt /var/mail /var 2>/dev/null | sort -h | tail -100 || true
echo "--- swap and mail ---"
swapon --show --bytes
ls -ldh /var/swap /var/mail/joshan 2>/dev/null || true
if [[ -f /var/mail/joshan ]]; then
  echo "MAIL_SPOOL_BYTES=$(stat -c %s /var/mail/joshan)"
  echo "MAIL_SPOOL_MTIME=$(stat -c %y /var/mail/joshan)"
  echo "MAIL_SPOOL_MESSAGE_COUNT=$(grep -c '^From ' /var/mail/joshan || true)"
  echo "MAIL_SPOOL_OWNER=$(stat -c %U:%G /var/mail/joshan)"
elif [[ -d /var/mail/joshan ]]; then
  find /var/mail/joshan -maxdepth 2 -type f -printf 'MAIL_FILE=%p bytes=%s mtime=%TY-%Tm-%TdT%TH:%TM:%TS\\n'
fi
echo "RESULT=PASS"
