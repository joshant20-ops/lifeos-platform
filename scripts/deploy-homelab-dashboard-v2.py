#!/usr/bin/env python3
"""Audit/fix the live Home Assistant Homelab dashboard without touching LifeOS/House Status."""
import copy, json, shutil, time
from pathlib import Path

ROOT=Path('/opt/stacks/homeassistant/config/.storage')
DASH=ROOT/'lovelace.dashboard_homelab'
BACKUPS=ROOT/'.lifeos-backups'

doc=json.loads(DASH.read_text())
views=doc['data']['config']['views']
by={v.get('path'):copy.deepcopy(v) for v in views if isinstance(v,dict)}
for p in ('overview','network','tower'):
    if p not in by: raise SystemExit(f'FAIL: missing Homelab view {p}')

# Overview: infrastructure only. Remove duplicated execution-safety/network detail blocks.
overview={
 'title':'Overview','path':'overview','icon':'mdi:server-network',
 'type':'sections','max_columns':2,
 'sections':[
  {'type':'grid','cards':[
   {'type':'heading','heading':'Homelab status','icon':'mdi:server-network'},
   {'type':'entities','title':'Host status','show_header_toggle':False,'entities':[
    {'entity':'sensor.execution_safety_docker_host_state','name':'Docker host'},
    {'entity':'sensor.execution_safety_z97_vm_host_state','name':'Tower / Z97'},
    {'entity':'sensor.execution_safety_pi3_oob_controller_state','name':'Pi3 OOB controller'}]},
   {'type':'entities','title':'Network identity','show_header_toggle':False,'entities':[
    {'entity':'sensor.network_identity_known_host_count','name':'Known hosts'},
    {'entity':'sensor.network_identity_allowed_host_count','name':'Allowed hosts'},
    {'entity':'sensor.network_identity_blocked_host_count','name':'Blocked hosts'},
    {'entity':'sensor.network_identity_summary','name':'Summary'}]}
  ]}
 ]}

network=by['network']
network.update({'title':'Network','path':'network','icon':'mdi:lan','type':'sections','max_columns':2})
# Strip the redundant introductory markdown card; headings are supplied by entity-card titles.
network['sections']=[{'type':'grid','cards':[c for c in network.get('cards',[]) if not (isinstance(c,dict) and c.get('type')=='markdown')]}]
network.pop('cards',None)

tower=by['tower']
tower.update({'title':'Tower','path':'tower','icon':'mdi:server','type':'sections','max_columns':2})
cards=tower.get('cards',[])
status={'type':'entities','title':'Tower status','show_header_toggle':False,'entities':[
 {'entity':'binary_sensor.tower_pc_tower_accessible','name':'Reachable'},
 {'entity':'sensor.tower_pc_tower_status','name':'Status'}]}
# Put status first so unavailable telemetry is clearly explained when the Tower is asleep/offline.
tower['sections']=[{'type':'grid','cards':[status]+cards}]
tower.pop('cards',None)

doc['data']['config']['views']=[overview,network,tower]
BACKUPS.mkdir(parents=True,exist_ok=True)
stamp=time.strftime('%Y%m%d-%H%M%S')
backup=BACKUPS/f'lovelace.dashboard_homelab.before-v2.{stamp}.json'
shutil.copy2(DASH,backup)
tmp=DASH.with_name(DASH.name+'.v2.tmp')
tmp.write_text(json.dumps(doc,indent=2)+'\n')
json.loads(tmp.read_text())
tmp.replace(DASH)
print('HOMELAB_V2_DEPLOY=PASS')
print('BACKUP='+str(backup))
print('VIEWS='+repr([(v.get('title'),v.get('path')) for v in doc['data']['config']['views']]))
