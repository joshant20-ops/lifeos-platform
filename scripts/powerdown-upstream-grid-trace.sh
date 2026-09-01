#!/usr/bin/env bash
set -Eeuo pipefail
START=$(date +%s)
CONF=/opt/stacks/homeassistant/config
ENTITY=sensor.lifeos_energy_grid_import

echo '===== POWER DOWN UPSTREAM GRID TRACE ====='
echo 'Expected: <15 sec'
date -Is

echo
echo '===== 1/4 — ENTITY REGISTRY ====='
python3 - "$CONF/.storage/core.entity_registry" "$ENTITY" <<'PY'
import json,sys
p,e=sys.argv[1:]
d=json.load(open(p))
for x in d.get('data',{}).get('entities',[]):
    if x.get('entity_id')==e:
        for k in ('entity_id','platform','unique_id','config_entry_id','device_id','original_name','name'):
            print(f'{k.upper()}={x.get(k)}')
        break
else: print('ENTITY_REGISTRY_MATCH=none')
PY

echo
echo '===== 2/4 — LIVE STATE ====='
python3 - "$CONF/home-assistant_v2.db" "$ENTITY" <<'PY'
import sqlite3,sys,datetime
p,e=sys.argv[1:]
con=sqlite3.connect(f'file:{p}?mode=ro',uri=True)
r=con.execute('''select s.state,s.last_changed_ts,s.last_updated_ts from states s join states_meta m on m.metadata_id=s.metadata_id where m.entity_id=? order by s.state_id desc limit 5''',(e,)).fetchall()
for i,(state,lc,lu) in enumerate(r):
    def f(x): return datetime.datetime.fromtimestamp(x,datetime.timezone.utc).isoformat() if x else None
    print(f'ROW_{i}_STATE={state} LAST_CHANGED={f(lc)} LAST_UPDATED={f(lu)}')
con.close()
PY

echo
echo '===== 3/4 — CONFIG REFERENCES ====='
grep -RIn --exclude='*.db*' --exclude='*.log*' --exclude-dir='.git' "$ENTITY\|lifeos_energy_grid_import" "$CONF" 2>/dev/null | head -80 || true

echo
echo '===== 4/4 — RELATED SERVICES / CONTAINERS ====='
systemctl list-units --all --type=service --no-pager | grep -Ei 'lifeos.*energy|mqtt|mosquitto|predbat|enphase|envoy' || true
docker ps --format '{{.Names}}\t{{.Status}}' | grep -Ei 'lifeos|mqtt|mosquitto|predbat|enphase|envoy|homeassistant' || true

echo
printf '[%ds] TRACE_COMPLETE=PASS\n' "$(( $(date +%s)-START ))"
