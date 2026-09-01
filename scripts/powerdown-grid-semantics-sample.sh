#!/usr/bin/env bash
set -Eeuo pipefail
SECRET=/usr/local/sbin/lifeos-secret
[ "$(id -u)" -eq 0 ] || { echo "FAIL: run with sudo/root"; exit 1; }
[ -x "$SECRET" ] || { echo "FAIL: lifeos-secret helper missing"; exit 1; }

echo "===== POWER DOWN GRID SEMANTICS SAMPLE ====="
echo "Expected: ~30 sec"
date -Is

"$SECRET" exec homeassistant.long_lived_access_token HA_TOKEN python3 - <<'PY'
import json, os, time, urllib.request
from datetime import datetime

HA='http://127.0.0.1:8123'
ENERGY='http://127.0.0.1:8110/api/energy/current'
ENV='sensor.envoy_122425011227_current_net_power_consumption'
LIFE='sensor.lifeos_energy_grid_import'
DER='sensor.lifeos_grid_import_power'
headers={'Authorization':'Bearer '+os.environ['HA_TOKEN']}

def ha(e):
    req=urllib.request.Request(HA+'/api/states/'+e,headers=headers)
    with urllib.request.urlopen(req,timeout=10) as r: return json.load(r)

def energy():
    with urllib.request.urlopen(ENERGY,timeout=10) as r: return json.load(r)

for i in range(8):
    t=time.time()
    a=energy(); e=ha(ENV); l=ha(LIFE); d=ha(DER)
    env_kw=float(e['state'])
    print(json.dumps({
      'sample':i+1,
      'epoch':round(t,3),
      'api_grid_w':a.get('grid_w'),
      'api_grid_import_w':a.get('grid_import_w'),
      'api_grid_export_w':a.get('grid_export_w'),
      'api_source':a.get('source'),
      'api_provider':a.get('provider'),
      'api_age_seconds':a.get('age_seconds'),
      'envoy_net_w':round(env_kw*1000,1),
      'envoy_import_if_positive_w':round(max(0,env_kw*1000),1),
      'envoy_export_if_negative_w':round(max(0,-env_kw*1000),1),
      'lifeos_rest_import_w':round(float(l['state'])*1000,1),
      'derived_import_w':round(float(d['state']),1),
      'envoy_last_reported':e.get('last_reported') or e.get('last_updated'),
      'lifeos_last_reported':l.get('last_reported') or l.get('last_updated')
    },sort_keys=True,separators=(',',':')))
    if i < 7: time.sleep(4)
PY

echo "SAMPLE_COMPLETE=PASS"
