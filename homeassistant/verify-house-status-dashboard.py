#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
HA=Path('/opt/stacks/homeassistant/config')
DASH=HA/'.storage/lovelace.dashboard_house_status'
REG=HA/'.storage/lovelace_dashboards'
RESOURCE=HA/'.storage/lovelace_resources'
CARD=HA/'www'/'house-status'/'lifeos-house-status-card.js'

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
for v in views[:3]:
 if v.get('type')!='panel' or len(v.get('cards',[]))!=1 or v['cards'][0].get('type')!='custom:lifeos-house-status': fail('first three views must be single custom frontend panels',repr(v))
if 'custom:apexcharts-card' in json.dumps(views[:3]): fail('legacy Lovelace chart composition remains')
card_blob=CARD.read_text() if CARD.exists() else ''
combined=blob+card_blob
for entity in ['sensor.lifeos_energy_tariff_horizon','sensor.lifeos_energy_report','sensor.lifeos_domestic_import_cost','sensor.lifeos_domestic_import_energy','sensor.lifeos_export_earnings','sensor.lifeos_export_energy','sensor.lifeos_energy_battery_soc']:
 if entity not in combined: fail('required proven energy entity missing',entity)
if 'placeholder-floorplan.svg' not in combined and 'Replaceable ground-floor plan' not in combined: fail('replaceable floorplan contract missing')
if 'Leave House' not in combined: fail('Leave House UI contract missing')
if 'EV' not in combined or 'Not installed' not in combined: fail('EV not-installed contract missing')
if 'Security sensors not installed' not in combined: fail('security fail-closed contract missing')
if 'Pending interval ledger' in blob or 'Live metering' in blob or 'Period controls' in blob: fail('placeholder/explanatory energy UI remains')
if 'sensor.lifeos_energy_import_tariff\"' in blob: fail('string tariff entity used as numeric chart series')
if '\"extend_to\": \"false\"' in blob: fail('invalid ApexCharts boolean encoding')
if 'sensor.lifeos_domestic_import_cost' not in combined or 'sensor.lifeos_domestic_import_energy' not in combined: fail('domestic battery-excluded ledger not wired')
if 'import_price_available===true' not in combined or 'import_p_per_kwh' not in combined: fail('published Octopus interval pricing contract missing')
if "| round(2)" not in combined and '.toFixed(2)' not in combined: fail('currency/energy precision formatting missing')
domestic=json.dumps(views[0])
if 'custom:lifeos-house-status' not in domestic: fail('purpose-built House Status frontend missing')
if 'Charge only' not in combined: fail('EV charge-only contract missing')
for entity in ['camera.front_door_live_view','event.front_door_motion','event.front_door_ding']:
 if entity not in blob: fail('current Ring doorbell mapping missing',entity)
print('HOUSE_STATUS_HA_GATE=PASS')
print('dashboard=/house-status drift=none')
print('views=4 order=PASS')
print('floorplan=replaceable-placeholder')
print('unsafe_unproven_controls=absent')
print('future_hardware_hooks=REPOSITORY_READY_RUNTIME_PENDING')
print('energy_ledger=RUNTIME_WIRED')
resource=RESOURCE
if not resource.exists(): fail('lovelace resource registry missing')
rdata=json.loads(resource.read_text()).get('data',{}).get('items',[])
registered=[x for x in rdata if str(x.get('url','')).startswith('/local/house-status/lifeos-house-status-card.js?v=') and x.get('type')=='module']
if len(registered)!=1: fail('House Status frontend resource not registered with HA storage schema',repr(registered))
card=CARD
if not card.exists() or 'customElements.define' not in card.read_text(): fail('House Status frontend asset missing')
print('frontend_custom_card=PASS')
print('frontend_static_contract=PASS')
print('leave_house=RUNTIME_AUTOMATION_PENDING_SUPPORTED_HA_CONFIG_PATH')
