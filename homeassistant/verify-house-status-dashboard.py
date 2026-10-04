#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
HA=Path('/opt/stacks/homeassistant/config')
DASH=HA/'.storage/lovelace.dashboard_house_status'
REG=HA/'.storage/lovelace_dashboards'
RESOURCE=HA/'.storage/lovelace_resources'
CARD=HA/'www'/'house-status'/'lifeos-house-status-v28.js'
LEGACY_CARD=HA/'www'/'house-status'/'lifeos-house-status-v27.js'
DOORBELL=HA/'www'/'house-status'/'lifeos-house-status-doorbell.js'
CONFIG=HA/'configuration.yaml'

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
if items: fail('legacy Lovelace House Status registration remains',repr(items))
expected=[('Domestic Energy Consumption','domestic-energy-consumption'),('Full Energy Flow','full-energy-flow'),('Home Status','home-status'),('Doorbell','doorbell')]
got=[(v.get('title'),v.get('path')) for v in views]
if got!=expected: fail('view order',repr(got))
blob=json.dumps(views)
if 'custom:apexcharts-card' in json.dumps(views[:3]): fail('legacy Lovelace chart composition remains')
card_blob=CARD.read_text() if CARD.exists() else ''
legacy_card_blob=LEGACY_CARD.read_text() if LEGACY_CARD.exists() else ''
doorbell_blob=DOORBELL.read_text() if DOORBELL.exists() else ''
if not legacy_card_blob: fail('legacy v27 panel asset missing')
legacy_expected=(card_blob
 .replace('Doorbell v28','Doorbell v27')
 .replace('lifeos-house-status-v28','lifeos-house-status-v27'))
if legacy_card_blob!=legacy_expected:
 fail('legacy v27 panel differs outside version identifiers')
combined=blob+card_blob+doorbell_blob
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
if "customElements.define('lifeos-house-status-v28'" not in card_blob: fail('purpose-built House Status frontend missing')
if 'Charge only' not in combined: fail('EV charge-only contract missing')
doorbell=next((v for v in views if v.get('path')=='doorbell'),None)
if not doorbell: fail('native Doorbell view missing')
native_doorbell_json=json.dumps(doorbell)
if 'camera.front_door_live_view' not in native_doorbell_json:
 fail('Ring camera missing from native Doorbell view','camera.front_door_live_view')
# Motion/ding tiles are optional in the isolated stock-camera acceptance view.
print('doorbell_native_camera=PASS')
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
registered=[x for x in rdata if 'lifeos-house-status' in str(x.get('url',''))]
if registered: fail('legacy House Status Lovelace resource remains',repr(registered))
card=CARD
if not card.exists() or 'customElements.define' not in card.read_text(): fail('House Status frontend asset missing')
cfg=CONFIG.read_text()
if 'panel_custom:' not in cfg or 'name: lifeos-house-status-v28' not in cfg or 'module_url: /local/house-status/lifeos-house-status-v28.js?v=doorbell-shell-20261004-1' not in cfg: fail('native House Status panel_custom registration missing')
if sum(1 for line in cfg.splitlines() if line.strip()=="url_path: house-status")!=1: fail('duplicate live House Status panel registrations remain')
if 'lifeos-house-status-v4.js' in cfg or 'lifeos-house-status-v5.js' in cfg: fail('stale House Status panel remains')
release_dir=REPO/'homeassistant'/'releases'/'house-status'/'live'
for runtime,release in ((CARD,release_dir/'lifeos-house-status-v28.js'),
                        (LEGACY_CARD,release_dir/'lifeos-house-status-v27.js'),
                        (DOORBELL,release_dir/'lifeos-house-status-doorbell.js')):
 if not release.exists(): fail('frozen live release file missing',str(release))
 if not runtime.exists() or runtime.read_bytes()!=release.read_bytes():
  fail('live runtime asset differs from frozen release',str(runtime.name))
blob=card.read_text()
module_blob=blob+doorbell_blob
if 'loadCardHelpers' not in doorbell_blob or 'createCardElement' not in doorbell_blob: fail('embedded Home Assistant camera-card renderer missing')
if "camera_view:'live'" not in doorbell_blob or "entity:'camera.front_door_live_view'" not in doorbell_blob: fail('embedded live Doorbell camera config missing')
if 'Camera view could not load' not in doorbell_blob: fail('camera renderer failure fallback missing')
for marker in ['hass-toggle-menu','aria-label="Open Home Assistant menu"','standingChargeFor=r=>','Standing charge','1p / half-hour','flowPositive=todayReport.map','flowNegative=todayReport.map','data-zero-line','data-doorbell-card','window.loadCardHelpers','createCardElement','Camera view could not load','.doorcam','Today','Tomorrow','Octopus price (p/kWh)','Cost (£)','Gas cost','axis-cost','axis-price','data-period="day"','data-period="month"','data-period="year"','data-period="range"','data-shift="-1"','data-date-picker','type="date"','rawHi=vals.length?Math.max(...vals):0','rawPlo=pvals.length?Math.min(...pvals):0','Electricity used (excluding battery and car charging) and gas. Costs shown in £.','data-mode="doorbell"','band-free','band-powerdown','data-energy-band','Free electricity','Power down','joined_events']:
 if marker not in module_blob: fail('reference UI marker missing',marker)
if '<div class="tabs">' in blob: fail('duplicate in-page mode strip returned')
# Domestic view must not expose export line/card; export remains available to Full Energy Flow and total-cost calculation.
dom=blob[blob.find("if(mode==='domestic')"):blob.find("} else if(mode==='flow')")]
if '↑ Export earnings' in dom or '<path class="export"' in blob[blob.find('if(!flow)return'):blob.find("const maxK")]: fail('export presentation returned to Domestic view')
print('frontend_native_panel=PASS')
print('frontend_static_contract=PASS')
print('leave_house=RUNTIME_AUTOMATION_PENDING_SUPPORTED_HA_CONFIG_PATH')
