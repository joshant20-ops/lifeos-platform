#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER=${LIFEOS_HA_CONTAINER:-homeassistant}
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/mnt/docker-data/automation/backups/ha-tower-control-$STAMP"
TARGET=lovelace.lifeos_control

rollback() {
  rc=$?
  if (( rc == 0 )); then return; fi
  echo 'TOWER_DASHBOARD_ROLLBACK=attempting'
  if [[ -f "$BACKUP/$TARGET.before" ]]; then
    docker cp "$BACKUP/$TARGET.before" "$CONTAINER:/config/.storage/$TARGET" || true
    docker restart "$CONTAINER" >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap rollback ERR

[[ $EUID -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
docker exec "$CONTAINER" test -f "/config/.storage/$TARGET" || { echo 'ERROR=lifeos_control_dashboard_missing'; exit 1; }
mkdir -p "$BACKUP"
docker cp "$CONTAINER:/config/.storage/$TARGET" "$BACKUP/$TARGET.before"

docker exec -i "$CONTAINER" python3 - <<'PY'
import json, os, tempfile
from pathlib import Path

path=Path('/config/.storage/lovelace.lifeos_control')
doc=json.loads(path.read_text())
config=doc.get('data',{}).get('config',{})
views=config.get('views',[])

marker='LifeOS Tower managed dependency'

def lamp_card():
    return {
      'type':'markdown',
      'title':'Tower status',
      'content': """{% set s = states('sensor.tower_status') %}
{% if s == 'ACCESSIBLE' %}
## 🟢 Tower
**Powered and fully accessible**
{% elif s == 'POWERED_INACCESSIBLE' %}
## 🟡 Tower
**Powered but inaccessible**
{% elif s == 'OFF' %}
## <span style=\"color:#9e9e9e\">●</span> Tower
**Powered off**
{% else %}
## ⚪ Tower
**State unknown / power signal not configured**
{% endif %}

`{{ s }}` · Power: `{{ state_attr('sensor.tower_status','physical_power') or 'UNKNOWN' }}` · Access: `{{ 'YES' if is_state('binary_sensor.tower_accessible','on') else 'NO' }}`

<!-- LifeOS Tower managed dependency -->"""
    }

def wake_card():
    return {
      'type':'conditional',
      'conditions':[{'entity':'switch.tower_power','state':'off'}],
      'card':{
        'type':'button','entity':'switch.tower_power','name':'Wake Tower','icon':'mdi:power','show_state':True,
        'tap_action':{'action':'call-service','service':'switch.turn_on','target':{'entity_id':'switch.tower_power'}}
      }
    }

def shutdown_card():
    return {
      'type':'conditional',
      'conditions':[{'entity':'switch.tower_power','state':'on'}],
      'card':{
        'type':'button','entity':'switch.tower_power','name':'Shut down Tower','icon':'mdi:power','show_state':True,
        'tap_action':{
          'action':'call-service','service':'switch.turn_off','target':{'entity_id':'switch.tower_power'},
          'confirmation':{'text':'Shut down Tower and its hosted workloads gracefully?'}
        }
      }
    }

def unknown_card():
    return {
      'type':'conditional',
      'conditions':[{'entity':'switch.tower_power','state':'unknown'}],
      'card':{'type':'markdown','content':'**Tower power control is not configured yet.** LifeOS will not guess the MAC, power signal, or shutdown method.'}
    }

for view in views:
    if str(view.get('title') or '') not in {'Overview','Hosts'}:
        continue
    cards=view.setdefault('cards',[])
    if marker in json.dumps(cards):
        continue
    tower=[lamp_card(),wake_card(),shutdown_card(),unknown_card()]
    insert_at=2 if str(view.get('title'))=='Overview' else 1
    view['cards']=cards[:insert_at]+tower+cards[insert_at:]

fd,tmp=tempfile.mkstemp(prefix='.lovelace.lifeos_control.tower.',dir=str(path.parent),text=True)
try:
    with os.fdopen(fd,'w') as f:
        json.dump(doc,f,separators=(',',':'))
    os.replace(tmp,path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
print('TOWER_DASHBOARD_VIEWS=Overview,Hosts')
print('TOWER_STATUS_ENTITY=sensor.tower_status')
print('TOWER_POWER_ENTITY=switch.tower_power')
print('TOWER_ACCESS_ENTITY=binary_sensor.tower_accessible')
PY

docker restart "$CONTAINER" >/dev/null
for _ in $(seq 1 60); do
  [[ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)" == running ]] || { sleep 2; continue; }
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8123/ 2>/dev/null || true)"
  [[ "$code" =~ ^(200|301|302|401)$ ]] && break
  sleep 2
done
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8123/ 2>/dev/null || true)"
[[ "$code" =~ ^(200|301|302|401)$ ]] || { echo "ERROR=homeassistant_http_$code"; false; }

docker exec "$CONTAINER" python3 - <<'PY'
import json
from pathlib import Path
p=Path('/config/.storage/lovelace.lifeos_control')
text=p.read_text()
assert 'LifeOS Tower managed dependency' in text
assert 'sensor.tower_status' in text
assert 'switch.tower_power' in text
assert 'binary_sensor.tower_accessible' in text
json.loads(text)
print('TOWER_DASHBOARD_VALIDATION=PASS')
PY

echo 'RESULT=PASS'
echo 'TOWER_CONTROL_DASHBOARD_ADAPTED=YES'
echo 'TOWER_LIGHT=GRAY_OFF_YELLOW_INACCESSIBLE_GREEN_ACCESSIBLE'
echo 'TOWER_SHUTDOWN_CONFIRMATION=YES'
echo "BACKUP=$BACKUP"
