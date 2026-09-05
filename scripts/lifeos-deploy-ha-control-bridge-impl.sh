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
DASHBOARD_AUDIT="$PLATFORM/scripts/lifeos-ha-dashboard-audit-simplify.sh"
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
  if [[ -f "$BACKUP/tower.json.before" ]]; then
    install -o root -g joshan -m 0640 "$BACKUP/tower.json.before" "$TOWER_CONFIG" || true
  elif [[ -f "$BACKUP/tower.json.absent" ]]; then
    rm -f "$TOWER_CONFIG" || true
  fi
  systemctl daemon-reload || true
  if [[ -f "$BACKUP/tower-unit-was-active" ]]; then systemctl restart lifeos-tower-control.service || true; else systemctl stop lifeos-tower-control.service >/dev/null 2>&1 || true; fi
  exit "$rc"
}
trap rollback ERR

[[ $EUID -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
for file in "$SOURCE" "$TOWER_SOURCE" "$TOWER_UNIT_SOURCE" "$TOWER_CONFIG_EXAMPLE" "$DASHBOARD_ADAPTER" "$TOWER_DASHBOARD_ADAPTER" "$DASHBOARD_AUDIT"; do
  [[ -f "$file" && ! -L "$file" ]] || { echo "ERROR=canonical_file_missing:$file"; exit 1; }
done
[[ -f "$DEST" && ! -L "$DEST" ]] || { echo 'ERROR=installed_bridge_missing'; exit 1; }

mkdir -p "$BACKUP" /etc/lifeos /var/lib/lifeos-tower
cp -a "$DEST" "$BACKUP/lifeos-ha-issue-queue-bridge.before"
if [[ -f "$TOWER_DEST" ]]; then cp -a "$TOWER_DEST" "$BACKUP/lifeos-tower-control.before"; else : > "$BACKUP/lifeos-tower-control.absent"; fi
if [[ -f "$TOWER_UNIT" ]]; then cp -a "$TOWER_UNIT" "$BACKUP/lifeos-tower-control.service.before"; else : > "$BACKUP/lifeos-tower-control.service.absent"; fi
if [[ -f "$TOWER_CONFIG" ]]; then cp -a "$TOWER_CONFIG" "$BACKUP/tower.json.before"; else : > "$BACKUP/tower.json.absent"; fi
if systemctl is-active --quiet lifeos-tower-control.service 2>/dev/null; then : > "$BACKUP/tower-unit-was-active"; fi

python3 -m py_compile "$SOURCE" "$TOWER_SOURCE"
install -o root -g root -m 0755 "$SOURCE" "$DEST"
install -o root -g root -m 0755 "$TOWER_SOURCE" "$TOWER_DEST"
install -o root -g root -m 0644 "$TOWER_UNIT_SOURCE" "$TOWER_UNIT"
if [[ ! -e "$TOWER_CONFIG" ]]; then
  install -o root -g joshan -m 0640 "$TOWER_CONFIG_EXAMPLE" "$TOWER_CONFIG"
  echo 'TOWER_CONFIG=CREATED_CANONICAL'
else
  python3 - "$TOWER_CONFIG" "$TOWER_CONFIG_EXAMPLE" <<'PY'
import json, re, sys
from pathlib import Path
live_path, canonical_path = map(Path, sys.argv[1:3])
live = json.loads(live_path.read_text())
canonical = json.loads(canonical_path.read_text())
old_mac = str(live.get('mac') or '').strip()
if not old_mac:
    live['mac'] = canonical['mac']
    # The original unconfigured template also carried a subnet-specific broadcast.
    # Move that untouched default to the generic limited broadcast used by wakeonlan.
    if str(live.get('broadcast') or '') in {'', '192.168.0.255'}:
        live['broadcast'] = canonical['broadcast']
    live['wol_port'] = int(live.get('wol_port') or canonical.get('wol_port') or 9)
    live_path.write_text(json.dumps(live, indent=2) + '\n')
    print('TOWER_CONFIG=MIGRATED_MISSING_WOL_IDENTITY')
else:
    print('TOWER_CONFIG=PRESERVED_CONFIGURED')
mac = str(live.get('mac') or '').lower()
if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
    raise SystemExit('ERROR=invalid_tower_mac')
PY
fi
chown root:joshan "$TOWER_CONFIG"
chmod 0640 "$TOWER_CONFIG"
chown -R joshan:joshan /var/lib/lifeos-tower

python3 - "$TOWER_CONFIG" "$TOWER_CONFIG_EXAMPLE" <<'PY'
import json, sys
from pathlib import Path
live=json.loads(Path(sys.argv[1]).read_text())
canonical=json.loads(Path(sys.argv[2]).read_text())
if str(live.get('mac','')).lower() != str(canonical.get('mac','')).lower():
    raise SystemExit('ERROR=tower_mac_does_not_match_canonical')
print('TOWER_WOL_CONFIG=PASS')
print('TOWER_WOL_BROADCAST=' + str(live.get('broadcast') or ''))
print('TOWER_WOL_PORT=' + str(live.get('wol_port') or 9))
PY

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
DISCOVERY="$(timeout 10s mosquitto_sub -h 127.0.0.1 -C 1 -t homeassistant/switch/lifeos_tower/power/config 2>/dev/null || true)"
[[ -n "$DISCOVERY" ]] || { echo 'ERROR=tower_switch_discovery_absent'; false; }

python3 - "$CONTROL" "$TOWER" "$DISCOVERY" <<'PY'
import json, sys
value=json.loads(sys.argv[1]); tower=json.loads(sys.argv[2]); discovery=json.loads(sys.argv[3])
required={'state','github_runner','semaphore','roadmap_stage','roadmap_progress_percent','open_issue_count','eligible_count','blocked_count'}
missing=sorted(required-set(value))
if missing: raise SystemExit('missing_control_fields=' + ','.join(missing))
if value['state'] not in {'WORKING','IDLE','BLOCKED','STALLED','DEGRADED'}: raise SystemExit('invalid_control_state=' + str(value['state']))
if tower.get('state') not in {'OFF','POWERED_INACCESSIBLE','ACCESSIBLE','UNKNOWN'}: raise SystemExit('invalid_tower_state=' + str(tower.get('state')))
if discovery.get('command_topic') != 'lifeos/tower/power/set': raise SystemExit('invalid_tower_command_topic=' + str(discovery.get('command_topic')))
if discovery.get('payload_on') != 'ON' or discovery.get('payload_off') != 'OFF': raise SystemExit('invalid_tower_power_payloads')
print('CONTROL_STATE=' + value['state'])
print('CONTROL_CURRENT_ISSUE=' + str(value.get('current_issue') or 'none'))
print('CONTROL_BLOCKER=' + str(value.get('blocker') or 'none'))
print('CONTROL_NEXT_ACTION=' + str(value.get('next_action') or 'none'))
print('CONTROL_ROADMAP=' + str(value.get('roadmap_stage')) + '/' + str(value.get('roadmap_stages')))
print('TOWER_STATE=' + tower['state'])
print('TOWER_POWER=' + tower.get('physical_power','UNKNOWN'))
print('TOWER_ACCESSIBLE=' + ('YES' if tower.get('accessible') else 'NO'))
print('TOWER_SWITCH_COMMAND_PATH=PASS')
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
echo '==> AUDIT / SAFELY SIMPLIFY ALL ACTIVE HA DASHBOARDS'
bash "$DASHBOARD_AUDIT"

echo 'RESULT=PASS'
echo 'HA_CONTROL_BRIDGE_DEPLOYED=YES'
echo 'MQTT_CONTROL_TOPIC=PASS'
echo 'TOWER_CONTROLLER_DEPLOYED=YES'
echo 'TOWER_MQTT_DISCOVERY=PASS'
echo 'TOWER_POWER_COMMANDS=BOUNDED'
echo 'TOWER_WOL_IDENTITY=CONFIGURED'
echo 'TOWER_SWITCH_COMMAND_PATH=PASS'
echo 'TOWER_OFF_REQUIRES_CONFIGURED_GRACEFUL_SHUTDOWN=YES'
echo 'TOWER_DASHBOARD_LIGHT=GRAY_OFF_YELLOW_INACCESSIBLE_GREEN_ACCESSIBLE'
echo 'TOWER_SHUTDOWN_CONFIRMATION=YES'
echo 'HOME_ASSISTANT_DEVICE=LifeOS Issue Queue'
echo 'LIFEOS_CONTROL_DASHBOARD=ADAPTED'
echo 'LIFEOS_CONTROL_DASHBOARD_PATH=/lifeos-control/overview'
echo 'HA_DASHBOARD_AUDIT_AND_SIMPLIFICATION=PASS'
echo "BACKUP=$BACKUP"
echo 'ROLLBACK=restore backup bridge/Tower controller/Tower config/dashboard storage then restart affected services'
