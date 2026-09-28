#!/usr/bin/env python3
import copy, hashlib, json, shutil, time
from pathlib import Path

ROOT=Path('/opt/stacks/homeassistant/config/.storage')
HOMELAB=ROOT/'lovelace.dashboard_homelab'
LIFEOS=ROOT/'lovelace.dashboard_lifeos'
CONTROL=ROOT/'lovelace.lifeos_control'
HOUSE=ROOT/'lovelace.dashboard_house_status'
BACKUPS=ROOT/'.lifeos-backups'
FILES=(HOMELAB,LIFEOS,CONTROL)

def load(p):
    return json.loads(p.read_text())
def views(d):
    return d['data']['config']['views']
def bypath(vs,path):
    found=[v for v in vs if v.get('path')==path]
    if len(found)!=1: raise SystemExit(f'FAIL: expected one {path}, got {len(found)}')
    return copy.deepcopy(found[0])
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else 'absent'

house_before=digest(HOUSE)
docs={p:load(p) for p in FILES}
hv=views(docs[HOMELAB]); lv=views(docs[LIFEOS]); cv=views(docs[CONTROL])

# Preserve known-good live cards; only change dashboard ownership and human-facing titles.
infra=bypath(hv,'homelab'); infra['title']='Overview'; infra['path']='overview'; infra['icon']='mdi:server-network'
network=bypath(cv,'network'); network['title']='Network'; network['icon']='mdi:lan'
tower=bypath(cv,'z97'); tower['title']='Tower'; tower['path']='tower'; tower['icon']='mdi:server'
# Drop stale pre-migration Tower control cards; retain registered Z97 telemetry/history.
stale=('binary_sensor.tower_accessible','sensor.tower_lifecycle','switch.tower_power','switch.turn_on','switch.turn_off')
tower['cards']=[c for c in tower.get('cards',[]) if not any(x in json.dumps(c) for x in stale)]
docs[HOMELAB]['data']['config']['views']=[infra,network,tower]

pa=bypath(hv,'overview'); pa['title']='Overview'; pa['icon']='mdi:account-heart'
# System Status belongs to Control, not the personal-assistant landing page.
pa['cards']=[c for c in pa.get('cards',[]) if c.get('title')!='P01-B05 — System Status']
personal_docs=bypath(hv,'documents'); personal_docs['title']='Documents'; personal_docs['icon']='mdi:file-document-multiple'
chat=bypath(hv,'lifeos-chat'); chat['title']='Ask LifeOS'; chat['icon']='mdi:message-text'
important=bypath(hv,'important-information'); important['title']='Important Information'; important['icon']='mdi:information-outline'
docs[LIFEOS]['data']['config']['views']=[pa,personal_docs,chat,important]

control_overview=bypath(lv,'overview'); control_overview['title']='Overview'; control_overview['icon']='mdi:robot-industrial'
autonomous=bypath(lv,'autonomous-work'); autonomous['title']='Autonomous Work'; autonomous['icon']='mdi:source-pull'
energy_ai=bypath(lv,'energy-ai'); energy_ai['title']='Energy AI'; energy_ai['icon']='mdi:brain'
safety=bypath(cv,'execution-safety'); safety['title']='Execution Safety'; safety['icon']='mdi:shield-check'
docs[CONTROL]['data']['config']['views']=[control_overview,autonomous,energy_ai,safety]

BACKUPS.mkdir(parents=True,exist_ok=True)
stamp=time.strftime('%Y%m%d-%H%M%S')
for p in FILES:
    shutil.copy2(p,BACKUPS/f'{p.name}.before-role-separation.{stamp}.json')
for p,d in docs.items():
    tmp=p.with_name(p.name+'.role-separation.tmp')
    tmp.write_text(json.dumps(d,indent=2)+'
')
    json.loads(tmp.read_text())
    tmp.replace(p)

if digest(HOUSE)!=house_before:
    raise SystemExit('FAIL: House Status changed')
print('THREE_DASHBOARD_ROLE_DEPLOY=PASS')
print('HOUSE_STATUS_UNCHANGED='+house_before)
for p in FILES:
    d=load(p)
    print(p.name+'='+repr([(v.get('title'),v.get('path'),len(v.get('cards',[]))) for v in views(d)]))
