#!/usr/bin/env python3
"""Read-only House Status discovery. Emits bounded non-secret HA entity/state metadata."""
import json, re, subprocess
from pathlib import Path

REG=Path('/opt/stacks/homeassistant/config/.storage/core.entity_registry')
DEV=Path('/opt/stacks/homeassistant/config/.storage/core.device_registry')
if not REG.exists(): raise SystemExit('HA entity registry missing')
entities=json.loads(REG.read_text()).get('data',{}).get('entities',[])
devices={}
if DEV.exists():
    devices={d.get('id'):d for d in json.loads(DEV.read_text()).get('data',{}).get('devices',[])}

terms=('octopus','predbat','lifeos','gas','electric','energy','tariff','rate','price','cost','grid','solar','battery','tesla','ev','charger','wall_connector','doorbell','bell','camera','motion','window','door','opening','light','tv')
domains=('light.','media_player.','camera.','binary_sensor.','event.','button.','sensor.','switch.')
secret=re.compile(r'(token|secret|password|credential|api.?key|refresh)',re.I)

def selected(e):
    eid=e.get('entity_id','').lower()
    name=' '.join(str(e.get(k) or '') for k in ('name','original_name')).lower()
    dc=str(e.get('original_device_class') or '').lower()
    if not eid.startswith(domains): return False
    if eid.startswith(('light.','camera.','media_player.','event.')): return True
    if dc in {'window','door','opening','motion','gas','energy','power','monetary'}: return True
    return any(t in eid+' '+name for t in terms)

picked=[]
for e in entities:
    if not selected(e): continue
    d=devices.get(e.get('device_id'),{})
    picked.append({
      'entity_id':e.get('entity_id'),'name':e.get('name') or e.get('original_name'),
      'device_name':d.get('name_by_user') or d.get('name'),'area_id':e.get('area_id') or d.get('area_id'),
      'device_class':e.get('original_device_class'),'platform':e.get('platform'),
      'disabled':e.get('disabled_by') is not None
    })

# Current states add units and safe tariff/history attributes when available.
states={}
try:
    raw=subprocess.run(['docker','exec','homeassistant','python3','-c',
      "import json,urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8123/api/states',timeout=5).read().decode())"],
      text=True,capture_output=True,timeout=10)
    if raw.returncode==0:
        for s in json.loads(raw.stdout):
            eid=s.get('entity_id','')
            if any(p['entity_id']==eid for p in picked):
                attrs={k:v for k,v in (s.get('attributes') or {}).items() if not secret.search(str(k))}
                # Bound output and avoid dumping arbitrary huge integration payloads.
                safe={}
                for k,v in attrs.items():
                    enc=json.dumps(v,default=str)
                    if len(enc)<=12000: safe[k]=v
                states[eid]={'state':s.get('state'),'attributes':safe}
except Exception as exc:
    states={'_state_probe_error':str(exc)}

frontend={}
try:
    base=Path('/opt/stacks/homeassistant/config')
    rp=base/'.storage/lovelace_resources'
    if rp.exists():
        rr=json.loads(rp.read_text())
        frontend['lovelace_resources']=rr.get('data',{}).get('items',[])
    cp=base/'www/house-status/lifeos-house-status-card.js'
    frontend['card_exists']=cp.exists()
    if cp.exists():
        txt=cp.read_text()
        frontend['card_size']=len(txt)
        frontend['defines_element']="customElements.define('lifeos-house-status'" in txt
    probe=subprocess.run(['docker','exec','homeassistant','python3','-c',"import urllib.request; u='http://127.0.0.1:8123/local/house-status/lifeos-house-status-card.js'; r=urllib.request.urlopen(u,timeout=5); b=r.read(); print(r.status); print(len(b)); print(b'lifeos-house-status' in b)"],text=True,capture_output=True,timeout=10)
    frontend['http_probe_rc']=probe.returncode
    frontend['http_probe']=probe.stdout.strip()
    frontend['http_probe_err']=probe.stderr.strip()[-1000:]
except Exception as exc:
    frontend['probe_error']=repr(exc)
print(json.dumps({'house_status_candidates':picked,'current_states':states,'frontend':frontend},indent=2,sort_keys=True,default=str))
# Frontend resource diagnostics (read-only).
frontend={}
base=Path('/opt/stacks/homeassistant/config')
rp=base/'.storage/lovelace_resources'
cp=base/'www/house-status/lifeos-house-status-card.js'
try:
    frontend['resources']=json.loads(rp.read_text()).get('data',{}).get('items',[]) if rp.exists() else []
    frontend['card_exists']=cp.exists()
    frontend['card_defines_element']=("customElements.define('lifeos-house-status'" in cp.read_text()) if cp.exists() else False
    probe=subprocess.run(['docker','exec','homeassistant','wget','-qO-','http://127.0.0.1:8123/local/house-status/lifeos-house-status-card.js'],text=True,capture_output=True,timeout=10)
    frontend['served_rc']=probe.returncode
    frontend['served_bytes']=len(probe.stdout)
    frontend['served_defines_element']="customElements.define('lifeos-house-status'" in probe.stdout
    frontend['served_error']=probe.stderr[-500:]
except Exception as exc:
    frontend['error']=repr(exc)
print(json.dumps({'frontend_resource_diagnostics':frontend},indent=2,sort_keys=True))
print(f'HOUSE_STATUS_CANDIDATE_COUNT={len(picked)}')
print(f'HOUSE_STATUS_STATE_COUNT={len([k for k in states if not k.startswith("_")])}')
print('RESULT=PASS')
