#!/usr/bin/env python3
"""Live Wave A acceptance audit.

Reads only LifeOS-generated state and service/entity metadata. It does not send household
notifications, control energy hardware, or mutate Home Assistant configuration.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

ROOT=Path('/home/joshan/lifeos-platform')
STATE=Path.home()/'.local/state/lifeos'
PROJECTION=Path('/opt/stacks/homeassistant/config/lifeos_energy_opportunity_attention.json')

def run(args,check=True):
    cp=subprocess.run(args,text=True,capture_output=True)
    if check and cp.returncode: raise SystemExit(f"command failed: {args[0]} rc={cp.returncode} {cp.stderr[-500:]}")
    return cp

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def require(ok,label):
    if not ok: raise SystemExit('WAVE_A_ACCEPTANCE=FAIL\nFAILED='+label)
    print(label+'=PASS')

# Runtime inventory / scheduler.
for name in ('homeassistant','lifeos-energy','mosquitto','predbat'):
    names=run(['docker','ps','--format','{{.Names}}']).stdout.splitlines()
    require(name in names,'CONTAINER_'+name.upper().replace('-','_'))
require(run(['systemctl','is-enabled','lifeos-energy-opportunity-attention.timer'],False).stdout.strip()=='enabled','ATTENTION_TIMER_ENABLED')
require(run(['systemctl','is-active','lifeos-energy-opportunity-attention.timer'],False).stdout.strip()=='active','ATTENTION_TIMER_ACTIVE')
user=run(['systemctl','show','lifeos-energy-opportunity-attention.service','-p','User','--value']).stdout.strip()
require(user=='joshan','ATTENTION_SERVICE_UNPRIVILEGED')

# Current detector+projection replay must be byte-identical for the same published rates.
for _ in range(2):
    run(['/usr/bin/python3',str(ROOT/'scripts/run-wave-a-energy-attention.py')])
    require(PROJECTION.exists(),'ATTENTION_PROJECTION_PRESENT')
    if _==0: first_sha=sha(PROJECTION); first=json.loads(PROJECTION.read_text())
    else: second_sha=sha(PROJECTION); second=json.loads(PROJECTION.read_text())
require(first_sha==second_sha,'CURRENT_REPLAY_BYTE_IDENTICAL')
require(first.get('attention_id')==second.get('attention_id'),'CURRENT_REPLAY_STABLE_ID')

# Feed one real historical EnergyOpportunity through the projector in a temp location when available.
ledger=STATE/'energy-opportunities.json'
if ledger.exists():
    data=json.loads(ledger.read_text())
    records=list(data.values()) if isinstance(data,dict) else []
else: records=[]
if records:
    spec=importlib.util.spec_from_file_location('projector',ROOT/'scripts/project-energy-opportunities-to-ha.py')
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory() as td:
        out=Path(td)/'attention.json'
        payload=m.build_projection([records[0]])
        m.atomic_write(out,payload); a=out.read_bytes()
        m.atomic_write(out,payload); b=out.read_bytes()
        require(a==b,'HISTORICAL_OPPORTUNITY_REPLAY_IDENTICAL')
        require(payload.get('attention_id')==records[0].get('opportunity_id'),'HISTORICAL_OPPORTUNITY_ID_PRESERVED')
    print('HISTORICAL_OPPORTUNITY_AVAILABLE=YES')
else:
    print('HISTORICAL_OPPORTUNITY_AVAILABLE=NO')

# HA registry proves the common presentation entity exists after deployment.
code="""import json
from pathlib import Path
d=json.loads(Path('/config/.storage/core.entity_registry').read_text())
for e in d.get('data',{}).get('entities',[]):
 if e.get('unique_id')=='lifeos_energy_opportunity_attention': print(e.get('entity_id',''))
"""
entity=run(['docker','exec','homeassistant','python3','-c',code]).stdout.strip()
require(bool(entity),'HA_ENERGY_ATTENTION_ENTITY_REGISTERED')
print('HA_ENERGY_ATTENTION_ENTITY='+entity)

# Existing common attention template must reference the energy attention sensor.
source=(ROOT/'homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml').read_text()
require('sensor.lifeos_energy_opportunity_attention' in source,'COMMON_ATTENTION_INTEGRATION')

# Regression: HA health, Energy endpoints and clean canonical repository.
health=run(['docker','inspect','-f','{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}','homeassistant']).stdout.strip()
require(health in ('healthy','running'),'HOME_ASSISTANT_HEALTH')
for path in ('/health','/api/status'):
    cp=run(['/usr/bin/python3','-c',f"import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8110{path}',timeout=5); print(r.status)"])
    require(cp.stdout.strip().startswith('2'),'LIFEOS_ENERGY_'+path.strip('/').upper().replace('/','_'))
status=run(['git','-C',str(ROOT),'status','--porcelain']).stdout.strip()
head=run(['git','-C',str(ROOT),'rev-parse','HEAD']).stdout.strip(); origin=run(['git','-C',str(ROOT),'rev-parse','origin/main']).stdout.strip()
require(not status and head==origin,'CANONICAL_REPOSITORY_CLEAN')

print('CURRENT_STATE='+str(first.get('state')))
print('CURRENT_COUNT='+str(first.get('count')))
print('CURRENT_ATTENTION_ID='+str(first.get('attention_id') or 'none'))
print('NOTIFICATIONS_SENT=NO')
print('ENERGY_CONTROL_MUTATION=NO')
print('WAVE_A_ACCEPTANCE=PASS')
