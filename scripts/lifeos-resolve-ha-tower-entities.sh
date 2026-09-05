#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER=${LIFEOS_HA_CONTAINER:-homeassistant}
TARGET=/config/.storage/lovelace.lifeos_control

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }

docker exec -i "$CONTAINER" python3 - "$TARGET" <<'PY'
import json,os,sys,tempfile
from pathlib import Path

target=Path(sys.argv[1])
root=Path('/config/.storage')
registry_path=root/'core.entity_registry'
if not registry_path.exists():
    raise SystemExit('ERROR=ha_entity_registry_missing')
entries=json.loads(registry_path.read_text()).get('data',{}).get('entities',[])
by_uid={str(e.get('unique_id') or ''):str(e.get('entity_id') or '') for e in entries if e.get('unique_id') and e.get('entity_id')}
required={
    'lifeos_tower_status_v1':'sensor.tower_status',
    'lifeos_tower_power_v1':'switch.tower_power',
    'lifeos_tower_accessible_v1':'binary_sensor.tower_accessible',
}
resolved={}
for uid,old in required.items():
    eid=by_uid.get(uid,'')
    if not eid:
        raise SystemExit('ERROR=tower_entity_unique_id_missing:' + uid)
    resolved[old]=eid
if not target.exists():
    raise SystemExit('ERROR=lifeos_control_dashboard_missing')
doc=json.loads(target.read_text())

def rewrite(v):
    if isinstance(v,dict):
        return {k:rewrite(x) for k,x in v.items()}
    if isinstance(v,list):
        return [rewrite(x) for x in v]
    if isinstance(v,str):
        for old,new in resolved.items():
            v=v.replace(old,new)
        return v
    return v

out=rewrite(doc)
fd,tmp=tempfile.mkstemp(prefix='.lovelace.lifeos_control.tower-entities.',dir=str(target.parent),text=True)
try:
    with os.fdopen(fd,'w') as fh:
        json.dump(out,fh,separators=(',',':'))
    os.replace(tmp,target)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
text=json.dumps(out)
for old,new in resolved.items():
    if new not in text:
        raise SystemExit('ERROR=resolved_tower_entity_not_referenced:' + new)
    if old != new and old in text:
        raise SystemExit('ERROR=stale_tower_entity_reference:' + old)
print('TOWER_HA_ENTITY_RESOLUTION=PASS')
print('TOWER_HA_STATUS_ENTITY=' + resolved['sensor.tower_status'])
print('TOWER_HA_POWER_ENTITY=' + resolved['switch.tower_power'])
print('TOWER_HA_ACCESS_ENTITY=' + resolved['binary_sensor.tower_accessible'])
PY

docker restart "$CONTAINER" >/dev/null
for _ in $(seq 1 60); do
  state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
  [[ "$state" == running ]] || { sleep 2; continue; }
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8123/ 2>/dev/null || true)"
  [[ "$code" =~ ^(200|301|302|401)$ ]] && break
  sleep 2
done
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8123/ 2>/dev/null || true)"
[[ "$code" =~ ^(200|301|302|401)$ ]] || { echo "ERROR=homeassistant_http_$code"; exit 1; }
echo 'RESULT=PASS'
