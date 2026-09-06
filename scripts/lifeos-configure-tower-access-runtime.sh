#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG=/etc/lifeos/tower.json
UNIT=lifeos-tower-control.service
BROKER=127.0.0.1

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || { echo 'ERROR=tower_config_missing'; exit 1; }

EXPECTED_MAC="$(python3 - "$CONFIG" <<'PY'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
print(str(value.get('mac') or '').strip().lower())
PY
)"
[[ "$EXPECTED_MAC" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]] || { echo 'ERROR=tower_mac_invalid'; exit 1; }

TOWER_IP="$(python3 - "$EXPECTED_MAC" <<'PY'
import json,subprocess,sys
mac=sys.argv[1]
try:
    rows=json.loads(subprocess.check_output(['ip','-j','neigh'], text=True))
except Exception:
    rows=[]
for row in rows:
    if str(row.get('lladdr') or '').lower()==mac and ':' not in str(row.get('dst') or ''):
        print(row['dst'])
        break
PY
)"
[[ -n "$TOWER_IP" ]] || { echo 'ERROR=tower_mac_not_present_in_neighbor_table'; exit 1; }

timeout 3 bash -c "</dev/tcp/$TOWER_IP/22" 2>/dev/null || { echo "ERROR=tower_ssh_probe_failed:$TOWER_IP"; exit 1; }

AS_JOSHAN=(
  /usr/sbin/runuser -u joshan -- /usr/bin/env -i
  HOME=/home/joshan
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  LANG=C.UTF-8
)
SSH_OPTS=(
  -o BatchMode=yes -o IdentitiesOnly=no -o StrictHostKeyChecking=yes
  -o ConnectTimeout=5 -o ServerAliveInterval=5 -o ServerAliveCountMax=2
)
SSH_TARGET=''
for candidate in TowerPC.Tailor "$TOWER_IP"; do
  target="joshan@$candidate"
  if "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$target" 'printf READY' 2>/dev/null | grep -qx READY; then
    SSH_TARGET="$target"
    break
  fi
done
[[ -n "$SSH_TARGET" ]] || { echo 'ERROR=tower_existing_trusted_ssh_path_unavailable'; exit 1; }
"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'sudo -n /usr/bin/true' || {
  echo 'ERROR=tower_noninteractive_sudo_unavailable'
  exit 1
}
echo 'TOWER_SHUTDOWN_SSH_SUDO_PREFLIGHT=PASS'

BACKUP="$(mktemp /tmp/lifeos-tower-config.XXXXXX)"
cp -a "$CONFIG" "$BACKUP"
rollback() {
  rc=$?
  if (( rc != 0 )); then
    install -o root -g joshan -m 0640 "$BACKUP" "$CONFIG" || true
    systemctl restart "$UNIT" >/dev/null 2>&1 || true
    echo 'TOWER_ACCESS_CONFIG_ROLLBACK=RESTORED'
  fi
  rm -f "$BACKUP"
  exit "$rc"
}
trap rollback EXIT

python3 - "$CONFIG" "$TOWER_IP" <<'PY'
import json,os,sys,tempfile
from pathlib import Path
path=Path(sys.argv[1]); ip=sys.argv[2]
value=json.loads(path.read_text())
value['host']=ip
probe=value.get('access_probe') if isinstance(value.get('access_probe'),dict) else {}
probe['host']=ip
probe['port']=int(probe.get('port') or 22)
value['access_probe']=probe
value['shutdown']={
    'type':'linux_ssh',
    'host':ip,
    'user':'joshan',
}
fd,tmp=tempfile.mkstemp(prefix='.tower.',dir=str(path.parent),text=True)
try:
    with os.fdopen(fd,'w') as fh:
        json.dump(value,fh,indent=2)
        fh.write('\n')
    os.replace(tmp,path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
PY
chown root:joshan "$CONFIG"
chmod 0640 "$CONFIG"
systemctl restart "$UNIT"

STATE=''
for _ in $(seq 1 20); do
  STATE="$(timeout 3s mosquitto_sub -h "$BROKER" -C 1 -t lifeos/tower/state 2>/dev/null || true)"
  if python3 - "$STATE" <<'PY' >/dev/null 2>&1
import json,sys
v=json.loads(sys.argv[1])
raise SystemExit(0 if v.get('state')=='ACCESSIBLE' and v.get('accessible') is True else 1)
PY
  then
    break
  fi
  sleep 1
done
python3 - "$STATE" "$TOWER_IP" <<'PY'
import json,sys
v=json.loads(sys.argv[1])
ip=sys.argv[2]
if v.get('state')!='ACCESSIBLE' or v.get('accessible') is not True:
    raise SystemExit('ERROR=tower_not_accessible_after_runtime_probe:' + str(v.get('state')))
print('TOWER_RUNTIME_ACCESS_CONFIG=PASS')
print('TOWER_RUNTIME_ACCESS_HOST=' + ip)
print('TOWER_RUNTIME_ACCESS_PORT=22')
print('TOWER_RUNTIME_STATE=' + v['state'])
print('TOWER_RUNTIME_POWER=' + str(v.get('physical_power') or 'UNKNOWN'))
print('TOWER_SHUTDOWN_PROFILE=linux_ssh')
print('TOWER_SHUTDOWN_KEY_SOURCE=existing_service_account_identity')
PY

trap - EXIT
rm -f "$BACKUP"
echo 'RESULT=PASS'
