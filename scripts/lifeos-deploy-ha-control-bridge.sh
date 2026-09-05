#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
# Refresh the root-owned allow-listed gateway from the canonical repository before
# executing the already-proven HA bridge deployment. First prove the canonical
# /lifeos dashboard while /lifeos-control is absent; then build and independently
# verify the LifeOS Control / Z97 dashboard. This keeps the existing single-/lifeos
# verifier contract without treating the intentional control dashboard as legacy.
bash "$PLATFORM/scripts/lifeos-install-github-runner-gateway.sh"
bash "$PLATFORM/scripts/lifeos-deploy-ha-control-bridge-impl.sh"
# Resolve the live Tower IP from the already-canonical MAC and configure only the
# runtime access probe. This keeps private LAN addressing out of Git while allowing
# the controller to prove ACCESSIBLE when the machine is actually online.
bash "$PLATFORM/scripts/lifeos-configure-tower-access-runtime.sh"
python3 "$PLATFORM/homeassistant/deploy-lifeos-dashboard.py"

# The canonical dashboard deploy may restart Home Assistant. Wait for health before
# proving /lifeos and the absence of the legacy/control registration at this stage.
for _ in $(seq 1 60); do
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
  [[ "$health" == healthy || "$health" == running ]] && break
  sleep 2
done
health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
[[ "$health" == healthy || "$health" == running ]] || { echo "ERROR=homeassistant_health_before_canonical_verify:$health"; exit 1; }

python3 "$PLATFORM/homeassistant/verify-lifeos-dashboard.py"
echo 'CANONICAL_LIFEOS_DASHBOARD=PASS'

# Only after the canonical /lifeos verifier has passed, create the intentional
# control-plane dashboard and its Z97 masonry detail view. Resolve all MQTT-backed
# entities from stable unique_id values rather than assuming Home Assistant chose
# any particular entity_id after registry restores or renames.
bash "$PLATFORM/scripts/lifeos-adapt-ha-lifeos-dashboard.sh"
bash "$PLATFORM/scripts/lifeos-resolve-ha-control-entity.sh"
bash "$PLATFORM/scripts/lifeos-adapt-ha-tower-control.sh"
bash "$PLATFORM/scripts/lifeos-resolve-ha-tower-entities.sh"

for _ in $(seq 1 60); do
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
  [[ "$health" == healthy || "$health" == running ]] && break
  sleep 2
done
health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
[[ "$health" == healthy || "$health" == running ]] || { echo "ERROR=homeassistant_health_after_control_adapters:$health"; exit 1; }

docker exec -i homeassistant python3 - <<'PY'
import json
from pathlib import Path
p=Path('/config/.storage/lovelace.lifeos_control')
if not p.exists():
    raise SystemExit('ERROR=lifeos_control_storage_missing')
doc=json.loads(p.read_text())
views=doc.get('data',{}).get('config',{}).get('views',[])
z97=next((v for v in views if v.get('path')=='z97'),None)
if z97 is None:
    raise SystemExit('ERROR=z97_view_missing_after_ha_control_deploy')
if z97.get('type') != 'masonry':
    raise SystemExit('ERROR=z97_view_not_masonry:' + str(z97.get('type')))
cards=z97.get('cards')
if not isinstance(cards,list) or len(cards) < 10:
    raise SystemExit('ERROR=z97_renderable_cards_incomplete:' + str(len(cards or [])))
history=[c for c in cards if c.get('type')=='history-graph']
disks=[c for c in history if str(c.get('title') or '').startswith('Disk ')]
if len(history) < 7:
    raise SystemExit('ERROR=z97_history_graphs_incomplete:' + str(len(history)))
if len(disks) < 2:
    raise SystemExit('ERROR=z97_disk_graphs_incomplete:' + str(len(disks)))
registry=json.loads(Path('/config/.storage/core.entity_registry').read_text()).get('data',{}).get('entities',[])
by_uid={str(e.get('unique_id') or ''):str(e.get('entity_id') or '') for e in registry if e.get('unique_id') and e.get('entity_id')}
required=['lifeos_tower_status_v1','lifeos_tower_power_v1','lifeos_tower_accessible_v1']
missing=[x for x in required if not by_uid.get(x)]
if missing:
    raise SystemExit('ERROR=tower_entity_resolution_missing:' + ','.join(missing))
text=json.dumps(doc)
for uid in required:
    if by_uid[uid] not in text:
        raise SystemExit('ERROR=tower_entity_not_used:' + by_uid[uid])
print('Z97_HA_ONLY_DEPLOY=PASS')
print('Z97_VIEW_TYPE=masonry')
print('Z97_RENDERABLE_CARDS=' + str(len(cards)))
print('Z97_HISTORY_GRAPHS=' + str(len(history)))
print('Z97_DISK_GRAPHS=' + str(len(disks)))
print('TOWER_HA_RESOLVED_ENTITIES=PASS')
PY

TOWER_STATE="$(timeout 5s mosquitto_sub -h 127.0.0.1 -C 1 -t lifeos/tower/state 2>/dev/null || true)"
python3 - "$TOWER_STATE" <<'PY'
import json,sys
value=json.loads(sys.argv[1])
if value.get('state') != 'ACCESSIBLE' or value.get('accessible') is not True:
    raise SystemExit('ERROR=tower_runtime_state_not_accessible:' + str(value.get('state')))
print('TOWER_RUNTIME_STATE_FINAL=ACCESSIBLE')
print('TOWER_RUNTIME_POWER_FINAL=' + str(value.get('physical_power') or 'UNKNOWN'))
PY

echo 'LIFEOS_CONTROL_Z97=PASS'
