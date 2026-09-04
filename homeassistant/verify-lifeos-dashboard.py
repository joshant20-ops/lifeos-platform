#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
HA=Path('/opt/stacks/homeassistant/config')
DASH=HA/'.storage/lovelace.dashboard_lifeos'
REG=HA/'.storage/lovelace_dashboards'

def run(cmd):
    return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)

def fail(name, detail=''):
    print(f'FAIL: {name}')
    if detail: print(detail)
    print('===== DIAGNOSTICS =====')
    for label,cmd in [
        ('git',['git','status','--short','--branch']),
        ('drift',[sys.executable,'homeassistant/deploy-lifeos-dashboard.py','--check']),
        ('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}'])]:
        r=run(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip())
    try:
        d=json.loads(DASH.read_text())
        print('--- views ---')
        for v in d['data']['config']['views']:
            print(v.get('path'), 'cards=',len(v.get('cards',[])))
    except Exception as e: print('dashboard:',repr(e))
    raise SystemExit(1)

# Re-exec once with root because HA .storage permissions vary.
if os.geteuid()!=0:
    os.execvp('sudo',['sudo',sys.executable,str(Path(__file__).resolve())])

r=run([sys.executable,'homeassistant/deploy-lifeos-dashboard.py','--check'])
if r.returncode or 'DRIFT: none' not in r.stdout:
    fail('repository/runtime drift',(r.stdout+r.stderr).strip())

try:
    reg=json.loads(REG.read_text()).get('data',{}).get('items',[])
except Exception as e: fail('dashboard registry',repr(e))
lifeos=[x for x in reg if x.get('url_path')=='lifeos']
legacy=[x for x in reg if x.get('url_path')=='lifeos-control']
if len(lifeos)!=1 or legacy:
    fail('dashboard registration',f'lifeos={len(lifeos)} legacy={len(legacy)}')

try:
    d=json.loads(DASH.read_text()); views=d['data']['config']['views']; by={v.get('path'):v for v in views}
except Exception as e: fail('dashboard JSON',repr(e))
for path,count in {'overview':7,'energy-ai':11,'autonomous-work':8}.items():
    got=len(by.get(path,{}).get('cards',[]))
    if got!=count: fail('dashboard structure',f'{path}: expected={count} actual={got}')
blob=json.dumps(by['overview'])
required=['sensor.tower_pc_tower_status','binary_sensor.tower_pc_tower_accessible','switch.tower_pc_tower_power']
missing=[x for x in required if x not in blob]
if missing: fail('Tower controls in dashboard','missing='+','.join(missing))

r=subprocess.run(['docker','exec','homeassistant','python3','-c',"import json; d=json.load(open('/config/.storage/core.entity_registry')); print('\\n'.join(e.get('entity_id','') for e in d.get('data',{}).get('entities',[])))"],text=True,capture_output=True)
if r.returncode: fail('HA entity registry',(r.stdout+r.stderr).strip())
missing=[x for x in required if x not in set(r.stdout.splitlines())]
if missing: fail('Tower entities registered','missing='+','.join(missing))

print('LIFEOS_HA_GATE=PASS')
print('dashboard=/lifeos legacy=absent drift=none')
print('views=overview:7,energy-ai:11,autonomous-work:8 tower_controls=3/3')
