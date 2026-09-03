#!/usr/bin/env bash
set -Eeuo pipefail

CONTAINER=${LIFEOS_HA_CONTAINER:-homeassistant}
TARGETS=(
  sensor.predbat_enphase_5731818_battery_power
  sensor.predbat_enphase_5731818_grid_power
  sensor.predbat_enphase_5731818_load_power
  sensor.predbat_enphase_5731818_pv_power
  sensor.predbat_enphase_5731818_soc_percent
)

echo 'HA_ENERGY_ENTITY_AUDIT_VERSION=1'
echo 'MUTATIONS=NONE'
docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo 'RESULT=FAIL'; echo 'BARRIER=homeassistant_container_missing'; exit 1; }

docker exec -i "$CONTAINER" python3 - "${TARGETS[@]}" <<'PY'
import json,sys
from pathlib import Path
root=Path('/config/.storage')
reg=root/'core.entity_registry'
registered={}
if reg.exists():
    data=json.loads(reg.read_text()).get('data',{}).get('entities',[])
    for e in data:
        if isinstance(e,dict) and e.get('entity_id'):
            registered[str(e['entity_id'])]=e

missing=[]
for entity in sys.argv[1:]:
    e=registered.get(entity)
    if e:
        disabled=e.get('disabled_by')
        hidden=e.get('hidden_by')
        print(f'ENTITY={entity} REGISTERED=yes DISABLED_BY={disabled or "none"} HIDDEN_BY={hidden or "none"}')
    else:
        print(f'ENTITY={entity} REGISTERED=no')
        missing.append(entity)
print('REGISTERED_COUNT='+str(len(sys.argv[1:])-len(missing)))
print('MISSING_COUNT='+str(len(missing)))
for e in missing: print('MISSING_ENTITY='+e)
print('AUDIT_RESULT=PASS')
PY

echo 'RESULT=PASS'
echo 'NOTE=switch.turn_on_and_switch.turn_off_are_services_not_entity_ids'
