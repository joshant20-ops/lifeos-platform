#!/usr/bin/env bash
set -Eeuo pipefail

START_EPOCH="$(date +%s)"
HA_CONFIG="/opt/stacks/homeassistant/config"
ENTITY="sensor.lifeos_grid_import_power"
ENVOY="sensor.envoy_122425011227_current_net_power_consumption"

elapsed(){ local n d; n="$(date +%s)"; d=$((n-START_EPOCH)); printf '[%dm%02ds]' $((d/60)) $((d%60)); }
section(){ echo; echo "===== $* ====="; }

section "POWER DOWN GRID SOURCE TRACE"
echo "Expected: <20 sec"
echo "$(date --iso-8601=seconds)"

section "1/6 — HOME ASSISTANT ENTITY REGISTRY"
python3 - "$HA_CONFIG/.storage/core.entity_registry" "$ENTITY" <<'PY'
import json,sys
p,e=sys.argv[1:]
try: d=json.load(open(p))
except Exception as x:
 print('ENTITY_REGISTRY_READ_ERROR='+repr(x)); raise SystemExit(0)
rows=[x for x in d.get('data',{}).get('entities',[]) if x.get('entity_id')==e]
if not rows: print('ENTITY_REGISTRY_MATCH=none')
for x in rows:
 for k in ('entity_id','platform','unique_id','config_entry_id','device_id','original_name','name'):
  print(f'{k.upper()}={x.get(k)}')
PY

section "2/6 — CONFIG ENTRY"
python3 - "$HA_CONFIG/.storage/core.entity_registry" "$HA_CONFIG/.storage/core.config_entries" "$ENTITY" <<'PY'
import json,sys
r,c,e=sys.argv[1:]
try: rd=json.load(open(r)); cd=json.load(open(c))
except Exception as x:
 print('CONFIG_ENTRY_READ_ERROR='+repr(x)); raise SystemExit(0)
ids={x.get('config_entry_id') for x in rd.get('data',{}).get('entities',[]) if x.get('entity_id')==e}
for x in cd.get('data',{}).get('entries',[]):
 if x.get('entry_id') in ids:
  for k in ('entry_id','domain','title','source','state','disabled_by'):
   print(f'{k.upper()}={x.get(k)}')
PY

section "3/6 — CONFIG/STORAGE REFERENCES"
grep -Rsn --exclude='home-assistant_v2.db*' --exclude='*.log*' --exclude='core.restore_state' --exclude='core.entity_registry' --exclude='core.config_entries' \
  -E 'lifeos_grid_import_power|LifeOS Grid Import|grid_import_power' "$HA_CONFIG" 2>/dev/null | head -120 || true

section "4/6 — LIVE HA STATES"
if command -v lifeos-secret >/dev/null 2>&1; then SECRET=lifeos-secret; elif [ -x /usr/local/sbin/lifeos-secret ]; then SECRET=/usr/local/sbin/lifeos-secret; else SECRET=''; fi
if [ -n "$SECRET" ]; then
  "$SECRET" exec homeassistant.long_lived_access_token HA_TOKEN python3 - "$ENTITY" "$ENVOY" <<'PY'
import json,os,sys,urllib.request
for e in sys.argv[1:]:
 req=urllib.request.Request('http://127.0.0.1:8123/api/states/'+e,headers={'Authorization':'Bearer '+os.environ['HA_TOKEN']})
 try:
  x=json.load(urllib.request.urlopen(req,timeout=5))
  print('ENTITY='+e)
  print('STATE='+str(x.get('state')))
  print('LAST_CHANGED='+str(x.get('last_changed')))
  print('LAST_UPDATED='+str(x.get('last_updated')))
  print('LAST_REPORTED='+str(x.get('last_reported')))
  print('ATTRIBUTES='+json.dumps(x.get('attributes',{}),sort_keys=True,separators=(',',':')))
 except Exception as ex: print('STATE_READ_ERROR='+e+' '+repr(ex))
PY
else
 echo 'LIFEOS_SECRET=missing'
fi

section "5/6 — LIKELY PRODUCERS"
systemctl list-units --type=service --all --no-legend 2>/dev/null | grep -Ei 'lifeos|energy|mqtt|envoy|grid|forecast|shadow' | head -100 || true
printf '\n--- files referencing entity outside HA config ---\n'
grep -Rsn --exclude='*.log*' --exclude='*.db*' -E 'lifeos_grid_import_power|LifeOS Grid Import' /usr/local/sbin /opt/lifeos-watch /opt/stacks/lifeos-energy /etc/systemd/system 2>/dev/null | head -160 || true

section "6/6 — HOME ASSISTANT HEALTH"
docker ps --filter name=homeassistant --format 'HA_CONTAINER={{.Status}}' 2>/dev/null || true
docker logs --since 60m homeassistant 2>&1 | grep -Ei 'lifeos_grid_import|template|mqtt|error|exception' | tail -100 || true

echo
echo "$(elapsed) TRACE_COMPLETE=PASS"
