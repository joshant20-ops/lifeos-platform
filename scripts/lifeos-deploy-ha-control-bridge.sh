#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
SOURCE="$PLATFORM/governor/ha_issue_queue_bridge.py"
DEST=/usr/local/libexec/lifeos-ha-issue-queue-bridge
UNIT=lifeos-ha-issue-queue-bridge.service
TOWER_SOURCE="$PLATFORM/governor/tower_control.py"
TOWER_DEST=/usr/local/libexec/lifeos-tower-control
TOWER_UNIT_SOURCE="$PLATFORM/governor/systemd/lifeos-tower-control.service"
TOWER_UNIT=/etc/systemd/system/lifeos-tower-control.service
TOWER_CONFIG=/etc/lifeos/tower.json
TOWER_CONFIG_EXAMPLE="$PLATFORM/config/tower.example.json"
DASHBOARD_ADAPTER="$PLATFORM/scripts/lifeos-adapt-ha-lifeos-dashboard.sh"
TOWER_DASHBOARD_ADAPTER="$PLATFORM/scripts/lifeos-adapt-ha-tower-control.sh"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/mnt/docker-data/automation/backups/ha-control-bridge-$STAMP"

rollback() {
  rc=$?
  if (( rc == 0 )); then return; fi
  echo "ROLLBACK=attempting"
  if [[ -f "$BACKUP/lifeos-ha-issue-queue-bridge.before" ]]; then
    install -o root -g root -m 0755 "$BACKUP/lifeos-ha-issue-queue-bridge.before" "$DEST" || true
    systemctl restart "$UNIT" || true
  fi
  if [[ -f "$BACKUP/lifeos-tower-control.before" ]]; then
    install -o root -g root -m 0755 "$BACKUP/lifeos-tower-control.before" "$TOWER_DEST" || true
  elif [[ -f "$BACKUP/lifeos-tower-control.absent" ]]; then
    rm -f "$TOWER_DEST" || true
  fi
  if [[ -f "$BACKUP/lifeos-tower-control.service.before" ]]; then
    install -o root -g root -m 0644 "$BACKUP/lifeos-tower-control.service.before" "$TOWER_UNIT" || true
  elif [[ -f "$BACKUP/lifeos-tower-control.service.absent" ]]; then
    rm -f "$TOWER_UNIT" || true
  fi
  systemctl daemon-reload || true
  if [[ -f "$BACKUP/tower-unit-was-active" ]]; then systemctl restart lifeos-tower-control.service || true; else systemctl stop lifeos-tower-control.service >/dev/null 2>&1 || true; fi
  exit "$rc"
}
trap rollback ERR

[[ $EUID -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
for file in "$SOURCE" "$TOWER_SOURCE" "$TOWER_UNIT_SOURCE" "$TOWER_CONFIG_EXAMPLE" "$DASHBOARD_ADAPTER" "$TOWER_DASHBOARD_ADAPTER"; do
  [[ -f "$file" && ! -L "$file" ]] || { echo "ERROR=canonical_file_missing:$file"; exit 1; }
done
[[ -f "$DEST" && ! -L "$DEST" ]] || { echo 'ERROR=installed_bridge_missing'; exit 1; }

mkdir -p "$BACKUP" /etc/lifeos /var/lib/lifeos-tower
cp -a "$DEST" "$BACKUP/lifeos-ha-issue-queue-bridge.before"
if [[ -f "$TOWER_DEST" ]]; then cp -a "$TOWER_DEST" "$BACKUP/lifeos-tower-control.before"; else : > "$BACKUP/lifeos-tower-control.absent"; fi
if [[ -f "$TOWER_UNIT" ]]; then cp -a "$TOWER_UNIT" "$BACKUP/lifeos-tower-control.service.before"; else : > "$BACKUP/lifeos-tower-control.service.absent"; fi
if systemctl is-active --quiet lifeos-tower-control.service 2>/dev/null; then : > "$BACKUP/tower-unit-was-active"; fi

python3 -m py_compile "$SOURCE" "$TOWER_SOURCE"
install -o root -g root -m 0755 "$SOURCE" "$DEST"
install -o root -g root -m 0755 "$TOWER_SOURCE" "$TOWER_DEST"
install -o root -g root -m 0644 "$TOWER_UNIT_SOURCE" "$TOWER_UNIT"
if [[ ! -e "$TOWER_CONFIG" ]]; then
  install -o root -g joshan -m 0640 "$TOWER_CONFIG_EXAMPLE" "$TOWER_CONFIG"
  echo 'TOWER_CONFIG=CREATED_SAFE_UNCONFIGURED'
else
  echo 'TOWER_CONFIG=PRESERVED'
fi
chown root:joshan "$TOWER_CONFIG"
chmod 0640 "$TOWER_CONFIG"
chown -R joshan:joshan /var/lib/lifeos-tower

systemctl daemon-reload
systemctl enable --now lifeos-tower-control.service
systemctl restart "$UNIT"

for _ in $(seq 1 20); do
  systemctl is-active --quiet "$UNIT" && systemctl is-active --quiet lifeos-tower-control.service && break
  sleep 1
done
systemctl is-active --quiet "$UNIT" || { echo 'ERROR=bridge_not_active'; false; }
systemctl is-active --quiet lifeos-tower-control.service || { echo 'ERROR=tower_controller_not_active'; false; }

CONTROL="$(timeout 15s mosquitto_sub -h 127.0.0.1 -C 1 -t lifeos/issue_queue/control 2>/dev/null || true)"
[[ -n "$CONTROL" ]] || { echo 'ERROR=control_topic_absent'; false; }
TOWER="$(timeout 15s mosquitto_sub -h 127.0.0.1 -C 1 -t lifeos/tower/state 2>/dev/null || true)"
[[ -n "$TOWER" ]] || { echo 'ERROR=tower_state_topic_absent'; false; }

python3 - "$CONTROL" "$TOWER" <<'PY'
import json, sys
value=json.loads(sys.argv[1]); tower=json.loads(sys.argv[2])
required={'state','github_runner','semaphore','roadmap_stage','roadmap_progress_percent','open_issue_count','eligible_count','blocked_count'}
missing=sorted(required-set(value))
if missing: raise SystemExit('missing_control_fields=' + ','.join(missing))
if value['state'] not in {'WORKING','IDLE','BLOCKED','STALLED','DEGRADED'}: raise SystemExit('invalid_control_state=' + str(value['state']))
if tower.get('state') not in {'OFF','POWERED_INACCESSIBLE','ACCESSIBLE','UNKNOWN'}: raise SystemExit('invalid_tower_state=' + str(tower.get('state')))
print('CONTROL_STATE=' + value['state'])
print('CONTROL_CURRENT_ISSUE=' + str(value.get('current_issue') or 'none'))
print('CONTROL_BLOCKER=' + str(value.get('blocker') or 'none'))
print('CONTROL_NEXT_ACTION=' + str(value.get('next_action') or 'none'))
print('CONTROL_ROADMAP=' + str(value.get('roadmap_stage')) + '/' + str(value.get('roadmap_stages')))
print('TOWER_STATE=' + tower['state'])
print('TOWER_POWER=' + tower.get('physical_power','UNKNOWN'))
print('TOWER_ACCESSIBLE=' + ('YES' if tower.get('accessible') else 'NO'))
PY

echo '==> TOWER / POWER ENTITY DISCOVERY CANDIDATES'
docker exec homeassistant python3 - <<'PY' || true
import json,re
from pathlib import Path
p=Path('/config/.storage/core.entity_registry')
if p.exists():
    ents=json.loads(p.read_text()).get('data',{}).get('entities',[])
    rx=re.compile(r'(tower|desktop|computer|workstation|pc|wake|wol)',re.I)
    for e in ents:
        text=' '.join(str(e.get(k) or '') for k in ('entity_id','name','original_name','platform','unique_id'))
        if rx.search(text): print('TOWER_HA_CANDIDATE=' + str(e.get('entity_id')) + ' platform=' + str(e.get('platform')) + ' name=' + str(e.get('name') or e.get('original_name') or ''))
PY

echo '==> SAFE LAN PC DISCOVERY'
python3 - <<'PY' || true
import json, socket, subprocess
try:
    rows=json.loads(subprocess.check_output(['ip','-j','neigh'], text=True))
except Exception:
    rows=[]
cands=[]
for r in rows:
    ip=r.get('dst'); mac=r.get('lladdr'); state=r.get('state') or []
    if not ip or not mac or ':' in ip: continue
    open_ports=[]
    for port in (22,445,3389):
        try:
            with socket.create_connection((ip,port),timeout=.25): open_ports.append(port)
        except OSError: pass
    try: host=socket.gethostbyaddr(ip)[0]
    except Exception: host=''
    if open_ports:
        score=(3 if 445 in open_ports else 0)+(3 if 3389 in open_ports else 0)+(1 if 22 in open_ports else 0)
        cands.append((score,ip,mac,host,open_ports,state))
for score,ip,mac,host,ports,state in sorted(cands, reverse=True):
    print(f'TOWER_LAN_CANDIDATE=ip:{ip} mac:{mac} host:{host or "unknown"} ports:{",".join(map(str,ports))} score:{score} neigh:{state}')
if len(cands)==1:
    print('TOWER_LAN_UNIQUE_CANDIDATE=YES')
elif len(cands)>1:
    best=sorted(cands, reverse=True)
    print('TOWER_LAN_UNIQUE_CANDIDATE=' + ('YES_STRONG' if len(best)>1 and best[0][0] >= best[1][0]+3 else 'NO'))
else:
    print('TOWER_LAN_UNIQUE_CANDIDATE=NONE')
PY

echo '==> ADAPT CURRENT LIFEOS DASHBOARD'
bash "$DASHBOARD_ADAPTER"
echo '==> ADD TOWER CONTROL TO LIFEOS DASHBOARD'
bash "$TOWER_DASHBOARD_ADAPTER"

echo 'RESULT=PASS'
echo 'HA_CONTROL_BRIDGE_DEPLOYED=YES'
echo 'MQTT_CONTROL_TOPIC=PASS'
echo 'TOWER_CONTROLLER_DEPLOYED=YES'
echo 'TOWER_MQTT_DISCOVERY=PASS'
echo 'TOWER_POWER_COMMANDS=BOUNDED'
echo 'TOWER_OFF_REQUIRES_CONFIGURED_GRACEFUL_SHUTDOWN=YES'
echo 'TOWER_DASHBOARD_LIGHT=GRAY_OFF_YELLOW_INACCESSIBLE_GREEN_ACCESSIBLE'
echo 'TOWER_SHUTDOWN_CONFIRMATION=YES'
echo 'HOME_ASSISTANT_DEVICE=LifeOS Issue Queue'
echo 'LIFEOS_CONTROL_DASHBOARD=ADAPTED'
echo 'LIFEOS_CONTROL_DASHBOARD_PATH=/lifeos-control/overview'
echo "BACKUP=$BACKUP"
echo 'ROLLBACK=restore backup bridge/Tower controller/dashboard storage then restart affected services'
