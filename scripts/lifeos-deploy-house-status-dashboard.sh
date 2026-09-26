#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
HA=/opt/stacks/homeassistant/config
DASH_TARGET="$HA/.storage/lovelace.dashboard_house_status"
REGISTRY="$HA/.storage/lovelace_dashboards"
ASSET_DIR="$HA/www/house-status"
ASSET_TARGET="$ASSET_DIR/placeholder-floorplan.svg"
CARD_TARGET="$ASSET_DIR/lifeos-house-status-card.js"
CARD_SOURCE="$PLATFORM/homeassistant/www/house-status/lifeos-house-status-card.js"
RESOURCES="$HA/.storage/lovelace_resources"
SOURCE_ASSET="$PLATFORM/homeassistant/www/house-status/placeholder-floorplan.svg"
DEPLOYER="$PLATFORM/homeassistant/deploy-house-status-dashboard.py"
VERIFIER="$PLATFORM/homeassistant/verify-house-status-dashboard.py"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="$HA/.storage/house-status-deploy-$STAMP"
HAD_DASH=0; HAD_ASSET=0; HAD_CARD=0; MUTATED=0
fail(){ echo "HOUSE_STATUS_DEPLOY=FAIL"; echo "ERROR=$*"; exit 1; }
rollback(){ rc=$?; if [[ "$MUTATED" -eq 1 && "$rc" -ne 0 ]]; then echo "HOUSE_STATUS_ROLLBACK=START"; if [[ "$HAD_DASH" -eq 1 ]]; then cp -a "$BACKUP_DIR/dashboard" "$DASH_TARGET"; else rm -f "$DASH_TARGET"; fi; cp -a "$BACKUP_DIR/registry" "$REGISTRY"; cp -a "$BACKUP_DIR/resources" "$RESOURCES"; if [[ "$HAD_ASSET" -eq 1 ]]; then cp -a "$BACKUP_DIR/asset" "$ASSET_TARGET"; else rm -f "$ASSET_TARGET"; fi; if [[ "$HAD_CARD" -eq 1 ]]; then cp -a "$BACKUP_DIR/card" "$CARD_TARGET"; else rm -f "$CARD_TARGET"; fi; docker restart homeassistant >/dev/null || true; echo "HOUSE_STATUS_ROLLBACK=COMPLETE"; fi; exit "$rc"; }
trap rollback EXIT
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "must_run_as_root"
[[ -f "$DEPLOYER" && -f "$VERIFIER" && -f "$SOURCE_ASSET" && -f "$CARD_SOURCE" ]] || fail "repository_sources_missing"
[[ -d "$HA/.storage" && -f "$REGISTRY" && -f "$RESOURCES" ]] || fail "ha_storage_missing"
python3 -m py_compile "$DEPLOYER" "$VERIFIER"
python3 -m json.tool "$PLATFORM/homeassistant/house-status-dashboard.json" >/dev/null
mkdir -p "$BACKUP_DIR" "$ASSET_DIR"; cp -a "$REGISTRY" "$BACKUP_DIR/registry"; cp -a "$RESOURCES" "$BACKUP_DIR/resources"
if [[ -f "$DASH_TARGET" ]]; then HAD_DASH=1; cp -a "$DASH_TARGET" "$BACKUP_DIR/dashboard"; fi
if [[ -f "$ASSET_TARGET" ]]; then HAD_ASSET=1; cp -a "$ASSET_TARGET" "$BACKUP_DIR/asset"; fi
if [[ -f "$CARD_TARGET" ]]; then HAD_CARD=1; cp -a "$CARD_TARGET" "$BACKUP_DIR/card"; fi
install -o root -g root -m 0644 "$SOURCE_ASSET" "$ASSET_TARGET"
install -o root -g root -m 0644 "$CARD_SOURCE" "$CARD_TARGET"; MUTATED=1
python3 "$DEPLOYER"
docker restart homeassistant >/dev/null
for _ in $(seq 1 60); do state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true); [[ "$state" == "healthy" || "$state" == "running" ]] && break; sleep 2; done
state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
[[ "$state" == "healthy" || "$state" == "running" ]] || fail "homeassistant_not_healthy"
python3 "$VERIFIER"
MUTATED=0; trap - EXIT
echo "HOUSE_STATUS_DEPLOY=PASS"
echo "HOUSE_STATUS_DASHBOARD=/house-status"
echo "HOUSE_STATUS_VIEWS=4"
echo "HOUSE_STATUS_BACKUP=$BACKUP_DIR"
