#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
HA=Path('/opt/stacks/homeassistant/config')
DASH=HA/'.storage/lovelace.dashboard_house_status'
REG=HA/'.storage/lovelace_dashboards'

def fail(name,detail=''):
 print('FAIL:',name); print(detail); raise SystemExit(1)

if os.geteuid()!=0:
 os.execvp('sudo',['sudo',sys.executable,str(Path(__file__).resolve())])
r=subprocess.run(['docker','inspect','-f','{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}','homeassistant'],text=True,capture_output=True)
if r.returncode or r.stdout.strip().lower() not in {'healthy','running'}: fail('Home Assistant health',(r.stdout+r.stderr).strip())
r=subprocess.run([sys.executable,'homeassistant/deploy-house-status-dashboard.py','--check'],cwd=REPO,text=True,capture_output=True)
if r.returncode: fail('repository/runtime drift',(r.stdout+r.stderr).strip())
try:
 reg=json.loads(REG.read_text()).get('data',{}).get('items',[])
 d=json.loads(DASH.read_text()); views=d['data']['config']['views']
except Exception as e: fail('dashboard storage',repr(e))
items=[x for x in reg if x.get('url_path')=='house-status']
if len(items)!=1 or items[0].get('title')!='House Status': fail('dashboard registration',repr(items))
expected=[('Domestic Energy Consumption','domestic-energy-consumption'),('Full Energy Flow','full-energy-flow'),('Home Status','home-status'),('Doorbell','doorbell')]
got=[(v.get('title'),v.get('path')) for v in views]
if got!=expected: fail('view order',repr(got))
blob=json.dumps(views)
for entity in ['sensor.lifeos_energy_tariff_horizon','sensor.lifeos_energy_report','sensor.lifeos_domestic_import_cost','sensor.lifeos_domestic_import_energy','sensor.lifeos_export_earnings','sensor.lifeos_export_energy','sensor.lifeos_energy_battery_soc']:
 if entity not in blob: fail('required proven energy entity missing',entity)
if 'placeholder-floorplan.svg' not in blob: fail('replaceable floorplan contract missing')
if 'Leave House' not in blob: fail('Leave House UI contract missing')
if 'EV' not in blob or 'Not installed' not in blob: fail('EV not-installed contract missing')
if 'House secure is intentionally not asserted' not in blob: fail('security fail-closed contract missing')
if 'Pending interval ledger' in blob or 'Live metering' in blob or 'Period controls' in blob: fail('placeholder/explanatory energy UI remains')
if 'sensor.lifeos_energy_import_tariff\"' in blob: fail('string tariff entity used as numeric chart series')
if '\"extend_to\": \"false\"' in blob: fail('invalid ApexCharts boolean encoding')
if 'Battery charging excluded' not in blob: fail('domestic battery exclusion not surfaced')
if "| round(2)" not in blob: fail('currency/energy precision formatting missing')
domestic=json.dumps(views[0])
if '\"type\": \"sections\"' not in domestic or '\"column_span\": 4' not in domestic: fail('domestic responsive full-width sections missing')
if 'no V2G/V2H' not in blob: fail('EV charge-only contract missing')
for entity in ['camera.front_door_live_view','event.front_door_motion','event.front_door_ding']:
 if entity not in blob: fail('current Ring doorbell mapping missing',entity)
print('HOUSE_STATUS_HA_GATE=PASS')
print('dashboard=/house-status drift=none')
print('views=4 order=PASS')
print('floorplan=replaceable-placeholder')
print('unsafe_unproven_controls=absent')
print('future_hardware_hooks=REPOSITORY_READY_RUNTIME_PENDING')
print('energy_ledger=RUNTIME_WIRED')
print('frontend_static_contract=PASS')
print('leave_house=RUNTIME_AUTOMATION_PENDING_SUPPORTED_HA_CONFIG_PATH')
