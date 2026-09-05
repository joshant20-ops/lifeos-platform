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
import json, os, re, tempfile
from pathlib import Path

path=Path('/config/.storage/lovelace.lifeos_control')
doc=json.loads(path.read_text())
config=doc.get('data',{}).get('config',{})
views=config.setdefault('views',[])

marker='LifeOS Tower managed dependency'
metrics_marker='LifeOS Z97 metrics managed view'

# Resolve MQTT-discovered entities by unique_id rather than guessed entity IDs.
registry={}
reg_path=Path('/config/.storage/core.entity_registry')
if reg_path.exists():
    try:
        reg=json.loads(reg_path.read_text())
        for e in reg.get('data',{}).get('entities',[]):
            uid=str(e.get('unique_id') or '')
            eid=str(e.get('entity_id') or '')
            if uid and eid:
                registry[uid]=eid
    except Exception:
        pass

def eid(uid):
    return registry.get(uid)

def entity(uid, name=None):
    value=eid(uid)
    if not value:
        return None
    row={'entity':value}
    if name:
        row['name']=name
    return row

def history(title, rows, hours=24):
    entities=[r for r in rows if r]
    if not entities:
        return None
    return {'type':'history-graph','title':title,'hours_to_show':hours,'refresh_interval':30,'entities':entities}

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

def metrics_button():
    return {
      'type':'button','name':'Z97 metrics','icon':'mdi:chart-line','show_state':False,
      'tap_action':{'action':'navigate','navigation_path':'/lifeos-control/z97'}
    }

def unknown_card():
    return {
      'type':'conditional',
      'conditions':[{'entity':'switch.tower_power','state':'unknown'}],
      'card':{'type':'markdown','content':'**Tower power control is not configured yet.** LifeOS will not guess the MAC, power signal, or shutdown method.'}
    }

# Replace previously managed Tower controls so new navigation is idempotent.
for view in views:
    if str(view.get('title') or '') not in {'Overview','Hosts'}:
        continue
    old=view.setdefault('cards',[])
    cards=[]
    for card in old:
        blob=json.dumps(card)
        if marker in blob or 'switch.tower_power' in blob or 'sensor.tower_status' in blob:
            continue
        cards.append(card)
    tower=[lamp_card(),wake_card(),shutdown_card(),metrics_button(),unknown_card()]
    insert_at=2 if str(view.get('title'))=='Overview' else 1
    view['cards']=cards[:insert_at]+tower+cards[insert_at:]

# Build dedicated Z97 view.
activity=eid('lifeos_tower_activity_v1')
cpu=eid('lifeos_tower_cpu_util_v1')
ram=eid('lifeos_tower_ram_util_v1')
cpu_temp=eid('lifeos_tower_cpu_temp_v1')
load=eid('lifeos_tower_load_1m_v1')
rx=eid('lifeos_tower_net_rx_v1')
tx=eid('lifeos_tower_net_tx_v1')
gpu=eid('lifeos_tower_gpu_util_v1')
gpu_temp=eid('lifeos_tower_gpu_temp_v1')
gpu_vram=eid('lifeos_tower_gpu_vram_v1')
gpu_power=eid('lifeos_tower_gpu_power_v1')

cards=[]
cards.append({'type':'markdown','content':f"# Z97 / TowerPC\nDedicated host metrics and activity history.\n\n<!-- {metrics_marker} -->"})

live=[]
for uid,name in [
    ('lifeos_tower_activity_v1','Activity'),
    ('lifeos_tower_cpu_util_v1','CPU'),
    ('lifeos_tower_ram_util_v1','RAM'),
    ('lifeos_tower_cpu_temp_v1','CPU temperature'),
    ('lifeos_tower_load_1m_v1','Load 1m'),
    ('lifeos_tower_gpu_util_v1','GPU'),
    ('lifeos_tower_gpu_temp_v1','GPU temperature'),
    ('lifeos_tower_gpu_vram_v1','GPU VRAM'),
    ('lifeos_tower_gpu_power_v1','GPU power'),
    ('lifeos_tower_net_rx_v1','Network receive'),
    ('lifeos_tower_net_tx_v1','Network transmit'),
]:
    row=entity(uid,name)
    if row:
        live.append(row)
if live:
    cards.append({'type':'entities','title':'Live metrics','show_header_toggle':False,'entities':live})
else:
    cards.append({'type':'markdown','title':'Telemetry','content':'Tower telemetry entities are not available yet. The metrics publisher must be running and MQTT discovery must have completed.'})

for card in [
    history('CPU & RAM — 24 hours',[{'entity':cpu,'name':'CPU'} if cpu else None, {'entity':ram,'name':'RAM'} if ram else None]),
    history('GPU utilisation & VRAM — 24 hours',[{'entity':gpu,'name':'GPU'} if gpu else None, {'entity':gpu_vram,'name':'VRAM'} if gpu_vram else None]),
    history('Temperatures — 24 hours',[{'entity':cpu_temp,'name':'CPU'} if cpu_temp else None, {'entity':gpu_temp,'name':'GPU'} if gpu_temp else None]),
    history('Network throughput — 24 hours',[{'entity':rx,'name':'Receive'} if rx else None, {'entity':tx,'name':'Transmit'} if tx else None]),
    history('Activity state — 24 hours',[{'entity':activity,'name':'Activity'} if activity else None]),
]:
    if card:
        cards.append(card)

# Discover every physical disk published by the metrics agent and create one
# live card + one 24h read/write graph per disk.
disks={}
pattern=re.compile(r'^lifeos_tower_disk_(.+)_(read|write|used)_v1$')
for uid,value in registry.items():
    m=pattern.match(uid)
    if not m:
        continue
    disk,metric=m.groups()
    disks.setdefault(disk,{})[metric]=value

for disk in sorted(disks):
    d=disks[disk]
    rows=[]
    for metric,label in [('used','Used'),('read','Read rate'),('write','Write rate')]:
        if d.get(metric):
            rows.append({'entity':d[metric],'name':label})
    cards.append({'type':'entities','title':f'Disk {disk}','show_header_toggle':False,'entities':rows})
    graph=history(f'Disk {disk} read / write — 24 hours',[
        {'entity':d['read'],'name':'Read'} if d.get('read') else None,
        {'entity':d['write'],'name':'Write'} if d.get('write') else None,
    ])
    if graph:
        cards.append(graph)

# Keep controls accessible from the detail page too.
cards += [wake_card(), shutdown_card()]

z97_view={'title':'Z97','path':'z97','icon':'mdi:desktop-tower-monitor','cards':cards}
replaced=False
for i,view in enumerate(views):
    if str(view.get('path') or '')=='z97' or str(view.get('title') or '')=='Z97':
        views[i]=z97_view
        replaced=True
        break
if not replaced:
    views.append(z97_view)

fd,tmp=tempfile.mkstemp(prefix='.lovelace.lifeos_control.tower.',dir=str(path.parent),text=True)
try:
    with os.fdopen(fd,'w') as f:
        json.dump(doc,f,separators=(',',':'))
    os.replace(tmp,path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
print('TOWER_DASHBOARD_VIEWS=Overview,Hosts,Z97')
print('TOWER_STATUS_ENTITY=sensor.tower_status')
print('TOWER_POWER_ENTITY=switch.tower_power')
print('TOWER_ACCESS_ENTITY=binary_sensor.tower_accessible')
print(f'TOWER_METRICS_ENTITIES={len([x for x in registry if x.startswith("lifeos_tower_")])}')
print(f'TOWER_METRICS_DISKS={len(disks)}')
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
assert 'LifeOS Z97 metrics managed view' in text
assert 'sensor.tower_status' in text
assert 'switch.tower_power' in text
doc=json.loads(text)
views=doc.get('data',{}).get('config',{}).get('views',[])
assert any(v.get('path')=='z97' for v in views)
print('TOWER_DASHBOARD_VALIDATION=PASS')
PY

echo 'RESULT=PASS'
echo 'TOWER_CONTROL_DASHBOARD_ADAPTED=YES'
echo 'TOWER_METRICS_VIEW=Z97'
echo 'TOWER_METRICS_HISTORY_HOURS=24'
echo 'TOWER_METRICS_DISKS=PER_PHYSICAL_DEVICE'
echo 'TOWER_IDLE_STATE=CPU_GPU_DISK_NETWORK'
echo 'TOWER_LIGHT=GRAY_OFF_YELLOW_INACCESSIBLE_GREEN_ACCESSIBLE'
echo 'TOWER_SHUTDOWN_CONFIRMATION=YES'
echo "BACKUP=$BACKUP"
