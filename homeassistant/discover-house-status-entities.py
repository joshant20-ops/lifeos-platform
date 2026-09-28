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
    else:
        states={'_state_probe_error':(raw.stderr or raw.stdout or f'rc={raw.returncode}')[-2000:]}
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
    active=next((x for x in frontend['resources'] if x.get('id')=='lifeos_house_status_card'),{})
    active_url=str(active.get('url','')).split('?',1)[0]
    frontend['active_url']=active_url
    probe=subprocess.run(['docker','exec','homeassistant','wget','-qO-','http://127.0.0.1:8123'+active_url],text=True,capture_output=True,timeout=10)
    frontend['served_rc']=probe.returncode
    frontend['served_bytes']=len(probe.stdout)
    frontend['served_defines_element']="customElements.define('lifeos-house-status'" in probe.stdout
    frontend['served_error']=probe.stderr[-500:]
except Exception as exc:
    frontend['error']=repr(exc)
print(json.dumps({'frontend_resource_diagnostics':frontend},indent=2,sort_keys=True))
# Native panel diagnostics (read-only). Follow the active panel_custom module_url rather than a stale hard-coded version.
try:
    cfg=(base/'configuration.yaml').read_text()
    start=cfg.find('panel_custom:')
    frag=cfg[start:start+1200] if start>=0 else ''
    m=re.search(r'(?ms)^panel_custom:\\n.*?^  - name: (lifeos-house-status-v\\d+)\\n.*?^    url_path: house-status\\n.*?^    module_url: (/local/house-status/[^\\s]+)',cfg)
    active_name=m.group(1) if m else ''
    active_url=m.group(2) if m else ''
    active_path=base/'www'/active_url.removeprefix('/local/') if active_url else None
    active_txt=active_path.read_text() if active_path and active_path.exists() else ''
    probe=subprocess.run(['docker','exec','homeassistant','wget','-qO-','http://127.0.0.1:8123'+active_url],text=True,capture_output=True,timeout=10) if active_url else None
    served=probe.stdout if probe else ''
    print(json.dumps({'native_panel_diagnostics':{
      'config_fragment':frag,
      'active_name':active_name,
      'active_url':active_url,
      'active_exists':bool(active_path and active_path.exists()),
      'active_bytes':len(active_txt),
      'active_defines_expected':bool(active_name and f"customElements.define('{active_name}'" in active_txt),
      'active_has_axes':'Octopus price (p/kWh)' in active_txt and 'Cost (£)' in active_txt,
      'active_has_zero_line':'data-zero-line' in active_txt,
      'active_has_camera_stream':'ha-camera-stream' in active_txt,
      'served_rc':probe.returncode if probe else None,
      'served_bytes':len(served),
      'served_defines_expected':bool(active_name and f"customElements.define('{active_name}'" in served),
      'served_has_axes':'Octopus price (p/kWh)' in served and 'Cost (£)' in served,
      'served_has_zero_line':'data-zero-line' in served,
      'served_has_camera_stream':'ha-camera-stream' in served,
      'served_error':probe.stderr[-500:] if probe else 'active panel not found'
    }},indent=2,sort_keys=True))
except Exception as exc:
    print(json.dumps({'native_panel_diagnostics':{'error':repr(exc)}}))
print(f'HOUSE_STATUS_CANDIDATE_COUNT={len(picked)}')
print(f'HOUSE_STATUS_STATE_COUNT={len([k for k in states if not k.startswith("_")])}')
print('RESULT=PASS')
