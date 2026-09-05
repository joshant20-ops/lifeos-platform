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
# control-plane dashboard and its Z97 masonry detail view. Resolve the control-state
# entity from MQTT discovery unique_id rather than assuming Home Assistant assigned
# the canonical entity_id; restored registries may legitimately suffix that ID.
bash "$PLATFORM/scripts/lifeos-adapt-ha-lifeos-dashboard.sh"
bash "$PLATFORM/scripts/lifeos-resolve-ha-control-entity.sh"
bash "$PLATFORM/scripts/lifeos-adapt-ha-tower-control.sh"

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
print('Z97_HA_ONLY_DEPLOY=PASS')
print('Z97_VIEW_TYPE=masonry')
print('Z97_RENDERABLE_CARDS=' + str(len(cards)))
print('Z97_HISTORY_GRAPHS=' + str(len(history)))
print('Z97_DISK_GRAPHS=' + str(len(disks)))
PY

echo 'LIFEOS_CONTROL_Z97=PASS'
