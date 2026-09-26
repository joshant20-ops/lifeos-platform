#!/usr/bin/env python3
"""Read-only discovery for House Status entity mapping. Emits candidates; never changes HA."""
import json
from pathlib import Path

REG=Path('/opt/stacks/homeassistant/config/.storage/core.entity_registry')
DEV=Path('/opt/stacks/homeassistant/config/.storage/core.device_registry')
if not REG.exists(): raise SystemExit('HA entity registry missing')
data=json.loads(REG.read_text()).get('data',{}).get('entities',[])
devices={}
if DEV.exists():
    devices={d.get('id'):d for d in json.loads(DEV.read_text()).get('data',{}).get('devices',[])}

def kind(e):
    eid=e.get('entity_id',''); dc=(e.get('original_device_class') or '').lower(); name=' '.join(str(e.get(k) or '') for k in ('name','original_name')).lower()
    if eid.startswith('camera.') and any(x in (eid+' '+name) for x in ('doorbell','front door','front_door','bell')): return 'doorbell_camera'
    if eid.startswith('binary_sensor.') and any(x in (eid+' '+name) for x in ('doorbell','front door','front_door','bell')) and any(x in (eid+' '+name+' '+dc) for x in ('motion','occupancy')): return 'doorbell_motion'
    if any(eid.startswith(x) for x in ('event.','binary_sensor.','sensor.')) and any(x in (eid+' '+name) for x in ('doorbell','front door','front_door','bell')) and any(x in (eid+' '+name) for x in ('press','ding','button','visitor')): return 'doorbell_press'
    if eid.startswith('media_player.') and ('tv' in name or dc=='tv'): return 'tv'
    if eid.startswith('light.'): return 'light'
    if eid.startswith('binary_sensor.') and dc in {'window','door','opening'}: return 'aperture'
    if eid.startswith('sensor.') and ('gas' in eid or 'gas' in name): return 'gas'
    if any(x in (eid+' '+name) for x in ('tesla','wall_connector','ev charger','evse')): return 'ev'
    return None

out=[]
for e in data:
    k=kind(e)
    if not k: continue
    d=devices.get(e.get('device_id'),{})
    out.append({
      'kind':k,'entity_id':e.get('entity_id'),'name':e.get('name') or e.get('original_name'),
      'device_name':d.get('name_by_user') or d.get('name'),'area_id':e.get('area_id') or d.get('area_id'),
      'disabled':e.get('disabled_by') is not None
    })
print(json.dumps({'house_status_candidates':out},indent=2,sort_keys=True))
print(f'HOUSE_STATUS_CANDIDATE_COUNT={len(out)}')
print('RESULT=PASS')
