#!/usr/bin/env bash
set -Eeuo pipefail

REPO=/home/joshan/lifeos-platform
HA=/opt/stacks/homeassistant/config
ASSET_SRC="$REPO/homeassistant/www/house-status/placeholder-floorplan.svg"
ASSET_DST="$HA/www/house-status/placeholder-floorplan.svg"

fail(){ echo "HOUSE_STATUS_DEPLOY=FAIL"; echo "HOUSE_STATUS_ERROR=$1"; exit "${2:-1}"; }

[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root
[[ -f "$REPO/homeassistant/house-status-dashboard.json" ]] || fail dashboard_source_missing
[[ -f "$REPO/homeassistant/deploy-house-status-dashboard.py" ]] || fail deployer_missing
[[ -f "$REPO/homeassistant/verify-house-status-dashboard.py" ]] || fail verifier_missing
[[ -f "$ASSET_SRC" ]] || fail floorplan_asset_missing
[[ -d "$HA/.storage" ]] || fail ha_storage_missing

python3 -m py_compile   "$REPO/homeassistant/deploy-house-status-dashboard.py"   "$REPO/homeassistant/verify-house-status-dashboard.py"
python3 -m json.tool "$REPO/homeassistant/house-status-dashboard.json" >/dev/null

mkdir -p "$(dirname "$ASSET_DST")"
if [[ -f "$ASSET_DST" ]]; then
  cp -a "$ASSET_DST" "$ASSET_DST.pre-house-status-deploy.$(date -u +%Y%m%dT%H%M%SZ).bak"
fi
install -m 0644 "$ASSET_SRC" "$ASSET_DST"

python3 "$REPO/homeassistant/deploy-house-status-dashboard.py"

# HA storage-mode dashboards are read by the frontend/backend runtime. Restart
# the container so registration/config is deterministically reloaded.
docker restart homeassistant >/dev/null
for _ in $(seq 1 60); do
  state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)"
  [[ "$state" == healthy || "$state" == running ]] && break
  sleep 2
done
[[ "$state" == healthy || "$state" == running ]] || fail homeassistant_not_healthy_after_restart

python3 "$REPO/homeassistant/verify-house-status-dashboard.py"
echo "HOUSE_STATUS_DEPLOY=PASS"
echo "HOUSE_STATUS_DASHBOARD=/house-status"
echo "HOUSE_STATUS_VIEWS=3"
