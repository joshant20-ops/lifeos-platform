#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER=${LIFEOS_HA_CONTAINER:-homeassistant}
TARGET=/config/.storage/lovelace.lifeos_control
UNIQUE_ID=lifeos_control_state_v1

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }

docker exec -i "$CONTAINER" python3 - "$UNIQUE_ID" "$TARGET" <<'PY'
import json, os, sys, tempfile
from pathlib import Path

unique_id=sys.argv[1]
target=Path(sys.argv[2])
root=Path('/config/.storage')
registry_path=root/'core.entity_registry'
if not registry_path.exists():
    raise SystemExit('ERROR=ha_entity_registry_missing')
registry=json.loads(registry_path.read_text()).get('data',{}).get('entities',[])
match=next((e for e in registry if str(e.get('unique_id') or '')==unique_id),None)
if not match:
    raise SystemExit('ERROR=lifeos_control_state_unique_id_missing')
entity_id=str(match.get('entity_id') or '')
if not entity_id:
    raise SystemExit('ERROR=lifeos_control_state_entity_id_empty')
if not target.exists():
    raise SystemExit('ERROR=lifeos_control_dashboard_missing')
doc=json.loads(target.read_text())

old='sensor.lifeos_control_state'

def rewrite(value):
    if isinstance(value,dict):
        return {k:rewrite(v) for k,v in value.items()}
    if isinstance(value,list):
        return [rewrite(v) for v in value]
    if isinstance(value,str):
        return value.replace(old,entity_id)
    return value

out=rewrite(doc)
fd,tmp=tempfile.mkstemp(prefix='.lovelace.lifeos_control.entity.',dir=str(target.parent),text=True)
try:
    with os.fdopen(fd,'w') as fh:
        json.dump(out,fh,separators=(',',':'))
    os.replace(tmp,target)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass

text=json.dumps(out)
if entity_id not in text:
    raise SystemExit('ERROR=resolved_control_entity_not_referenced')
print('LIFEOS_CONTROL_ENTITY_RESOLUTION=PASS')
print('LIFEOS_CONTROL_ENTITY_UNIQUE_ID='+unique_id)
print('LIFEOS_CONTROL_ENTITY_ID='+entity_id)
print('LIFEOS_CONTROL_ENTITY_WAS_CANONICAL=' + ('YES' if entity_id==old else 'NO'))
PY
