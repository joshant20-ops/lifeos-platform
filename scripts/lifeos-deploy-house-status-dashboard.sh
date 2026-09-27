#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
HA=/opt/stacks/homeassistant/config
DASH_TARGET="$HA/.storage/lovelace.dashboard_house_status"
REGISTRY="$HA/.storage/lovelace_dashboards"
ASSET_DIR="$HA/www/house-status"
ASSET_TARGET="$ASSET_DIR/placeholder-floorplan.svg"
CARD_TARGET="$ASSET_DIR/lifeos-house-status-v6.js"
CARD_SOURCE="$PLATFORM/homeassistant/www/house-status/lifeos-house-status-card.js"
RESOURCES="$HA/.storage/lovelace_resources"
CONFIG="$HA/configuration.yaml"
HA_CONFIG="$HA/configuration.yaml"
MODULE_INSTALLER="$PLATFORM/homeassistant/ensure-house-status-extra-module.py"
SOURCE_ASSET="$PLATFORM/homeassistant/www/house-status/placeholder-floorplan.svg"
DEPLOYER="$PLATFORM/homeassistant/deploy-house-status-dashboard.py"
VERIFIER="$PLATFORM/homeassistant/verify-house-status-dashboard.py"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="$HA/.storage/house-status-deploy-$STAMP"
HAD_DASH=0; HAD_ASSET=0; HAD_CARD=0; MUTATED=0
fail(){ echo "HOUSE_STATUS_DEPLOY=FAIL"; echo "ERROR=$*"; exit 1; }
rollback(){ rc=$?; if [[ "$MUTATED" -eq 1 && "$rc" -ne 0 ]]; then echo "HOUSE_STATUS_ROLLBACK=START"; if [[ "$HAD_DASH" -eq 1 ]]; then cp -a "$BACKUP_DIR/dashboard" "$DASH_TARGET"; else rm -f "$DASH_TARGET"; fi; cp -a "$BACKUP_DIR/registry" "$REGISTRY"; cp -a "$BACKUP_DIR/resources" "$RESOURCES"; cp -a "$BACKUP_DIR/configuration.yaml" "$CONFIG"; cp -a "$BACKUP_DIR/configuration.yaml" "$HA_CONFIG"; if [[ "$HAD_ASSET" -eq 1 ]]; then cp -a "$BACKUP_DIR/asset" "$ASSET_TARGET"; else rm -f "$ASSET_TARGET"; fi; if [[ "$HAD_CARD" -eq 1 ]]; then cp -a "$BACKUP_DIR/card" "$CARD_TARGET"; else rm -f "$CARD_TARGET"; fi; docker restart homeassistant >/dev/null || true; echo "HOUSE_STATUS_ROLLBACK=COMPLETE"; fi; exit "$rc"; }
trap rollback EXIT
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "must_run_as_root"
[[ -f "$DEPLOYER" && -f "$VERIFIER" && -f "$SOURCE_ASSET" && -f "$CARD_SOURCE" && -f "$MODULE_INSTALLER" ]] || fail "repository_sources_missing"
[[ -d "$HA/.storage" && -f "$REGISTRY" && -f "$RESOURCES" ]] || fail "ha_storage_missing"
python3 -m py_compile "$DEPLOYER" "$VERIFIER" "$MODULE_INSTALLER"
NODE_BIN=$(command -v node 2>/dev/null || find /opt/actions-runner-lifeos/externals -maxdepth 3 -type f -name node -perm -111 2>/dev/null | head -n1)
[[ -n "$NODE_BIN" ]] || fail "node_missing_for_frontend_syntax_gate"
"$NODE_BIN" --check "$CARD_SOURCE" || fail "house_status_frontend_js_syntax_invalid"
python3 -m json.tool "$PLATFORM/homeassistant/house-status-dashboard.json" >/dev/null
mkdir -p "$BACKUP_DIR" "$ASSET_DIR"; cp -a "$REGISTRY" "$BACKUP_DIR/registry"; cp -a "$RESOURCES" "$BACKUP_DIR/resources"; cp -a "$CONFIG" "$BACKUP_DIR/configuration.yaml"; cp -a "$HA_CONFIG" "$BACKUP_DIR/configuration.yaml"
if [[ -f "$DASH_TARGET" ]]; then HAD_DASH=1; cp -a "$DASH_TARGET" "$BACKUP_DIR/dashboard"; fi
if [[ -f "$ASSET_TARGET" ]]; then HAD_ASSET=1; cp -a "$ASSET_TARGET" "$BACKUP_DIR/asset"; fi
if [[ -f "$CARD_TARGET" ]]; then HAD_CARD=1; cp -a "$CARD_TARGET" "$BACKUP_DIR/card"; fi
install -o root -g root -m 0644 "$SOURCE_ASSET" "$ASSET_TARGET"
install -o root -g root -m 0644 "$CARD_SOURCE" "$CARD_TARGET"; MUTATED=1
python3 - "$CONFIG" <<'PY'
from pathlib import Path
import sys,re
p=Path(sys.argv[1]); s=p.read_text()
# Remove all prior LifeOS House Status panel registrations. Duplicate url_path entries make
# Home Assistant retain/resolve the stale panel even when a newer panel is added first.
lines=s.splitlines(True)
out=[]; i=0
while i < len(lines):
    if lines[i].startswith('  - name: lifeos-house-status') or lines[i].startswith('  - name: lifeos-house-status-v'):
        i+=1
        while i < len(lines) and not lines[i].startswith('  - name:') and not (lines[i] and not lines[i][0].isspace()):
            i+=1
        continue
    out.append(lines[i]); i+=1
s=''.join(out)
# Remove the former global extra-module hook; panel_custom owns module loading now.
s=re.sub(r'(?m)^\s*- /local/house-status/lifeos-house-status(?:-card|-v[0-9]+)?\.js(?:\?[^\s]+)?\s*$\n?', '', s)
# Install one native Home Assistant custom panel, outside Lovelace.
panel="""panel_custom:
  - name: lifeos-house-status-v6
    sidebar_title: House Status
    sidebar_icon: mdi:home-heart
    url_path: house-status
    module_url: /local/house-status/lifeos-house-status-v6.js
    require_admin: false
    config:
      mode: domestic
"""
# Replace an existing LifeOS panel block if present, otherwise append.
pat=r'(?ms)^panel_custom:\n(?:  - .*\n(?:    .*\n)*)*'
if 'name: lifeos-house-status-v6' in s:
    # Replace the existing LifeOS panel block deterministically, regardless of its prior module version.
    start=s.index('panel_custom:\n')
    name=s.index('  - name: lifeos-house-status-v6',start)
    next_item=s.find('\n  - name:',name+1)
    end=len(s) if next_item<0 else next_item+1
    s=s[:start]+panel+(s[end:] if next_item>=0 else '\n')
elif 'panel_custom:\n' in s:
    insert=panel.split('\n',1)[1]
    s=s.replace('panel_custom:\n','panel_custom:\n'+insert,1)
else:
    s=s.rstrip()+'\n\n'+panel
p.write_text(s)
PY
docker exec homeassistant python -m homeassistant --script check_config -c /config >/dev/null
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
