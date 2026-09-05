#!/usr/bin/env python3
import json, os, re, subprocess, sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
HA=Path('/opt/stacks/homeassistant/config')
DASH=HA/'.storage/lovelace.dashboard_lifeos'
REG=HA/'.storage/lovelace_dashboards'
TOWER_CONFIG=Path('/etc/lifeos/tower.json')
TOWER_CANONICAL=REPO/'config/tower.example.json'
TOWER_INSTALLED=Path('/usr/local/libexec/lifeos-tower-control')
TOWER_SOURCE=REPO/'governor/tower_control.py'

def run(cmd):
    return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)

def fail(name, detail=''):
    print(f'FAIL: {name}')
    if detail: print(detail)
    print('===== DIAGNOSTICS =====')
    for label,cmd in [
        ('git',['git','status','--short','--branch']),
        ('drift',[sys.executable,'homeassistant/deploy-lifeos-dashboard.py','--check']),
        ('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}']),
        ('tower-service',['systemctl','status','lifeos-tower-control.service','--no-pager','-l'])]:
        r=run(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip())
    try:
        d=json.loads(DASH.read_text())
        print('--- views ---')
        for v in d['data']['config']['views']:
            print(v.get('path'), 'cards=',len(v.get('cards',[])))
    except Exception as e: print('dashboard:',repr(e))
    raise SystemExit(1)

if os.geteuid()!=0:
    os.execvp('sudo',['sudo',sys.executable,str(Path(__file__).resolve())])

r=run(['docker','inspect','-f','{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}','homeassistant'])
if r.returncode:
    fail('Home Assistant container health',(r.stdout+r.stderr).strip())
ha_health=r.stdout.strip().lower()
if ha_health not in {'healthy','running'}:
    fail('Home Assistant container health',f'status={ha_health or "unknown"}')

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

# Do not call the control functional merely because its entity exists. Prove the
# controller is installed from this repo, active, configured with a valid canonical
# WOL identity, and that HA discovery points the switch at the bounded command topic.
r=run(['systemctl','is-active','lifeos-tower-control.service'])
if r.returncode or r.stdout.strip()!='active':
    fail('Tower controller active',(r.stdout+r.stderr).strip())
if not TOWER_SOURCE.is_file() or not TOWER_INSTALLED.is_file():
    fail('Tower controller files','source_or_installed_missing')
r=run(['cmp','-s',str(TOWER_SOURCE),str(TOWER_INSTALLED)])
if r.returncode:
    fail('Tower controller repository/runtime drift','installed controller differs from canonical source')

try:
    cfg=json.loads(TOWER_CONFIG.read_text())
    canonical=json.loads(TOWER_CANONICAL.read_text())
except Exception as e:
    fail('Tower WOL configuration',repr(e))
mac=str(cfg.get('mac') or '').lower()
expected=str(canonical.get('mac') or '').lower()
if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',mac):
    fail('Tower WOL configuration','invalid or missing MAC')
if not expected or mac!=expected:
    fail('Tower WOL configuration',f'canonical MAC mismatch configured={mac or "missing"}')
port=int(cfg.get('wol_port') or 0)
if not 1 <= port <= 65535:
    fail('Tower WOL configuration',f'invalid wol_port={port}')
if not str(cfg.get('broadcast') or '').strip():
    fail('Tower WOL configuration','broadcast missing')

r=run(['mosquitto_sub','-h','127.0.0.1','-C','1','-W','3','-t','homeassistant/switch/lifeos_tower/power/config'])
if r.returncode or not r.stdout.strip():
    fail('Tower MQTT switch discovery',(r.stdout+r.stderr).strip())
try:
    discovery=json.loads(r.stdout.strip())
except Exception as e:
    fail('Tower MQTT switch discovery',repr(e))
if discovery.get('command_topic')!='lifeos/tower/power/set':
    fail('Tower MQTT switch discovery',f"command_topic={discovery.get('command_topic')!r}")
if discovery.get('payload_on')!='ON' or discovery.get('payload_off')!='OFF':
    fail('Tower MQTT switch discovery','ON/OFF payload mapping invalid')

r=run(['mosquitto_sub','-h','127.0.0.1','-C','1','-W','3','-t','lifeos/tower/availability'])
if r.returncode or r.stdout.strip()!='online':
    fail('Tower controller MQTT availability',(r.stdout+r.stderr).strip() or r.stdout.strip())

print('LIFEOS_HA_GATE=PASS')
print(f'homeassistant={ha_health}')
print('dashboard=/lifeos legacy=absent drift=none')
print('views=overview:7,energy-ai:11,autonomous-work:8 tower_controls=3/3')
print('tower_controller=active drift=none')
print(f'tower_wol=CONFIGURED broadcast={cfg.get("broadcast")} port={port}')
print('tower_switch_command_path=lifeos/tower/power/set PASS')
print('tower_functional_claim=CONFIGURED_NOT_SIDE_EFFECT_TESTED')
