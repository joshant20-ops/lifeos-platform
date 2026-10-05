#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
HA=/opt/stacks/homeassistant/config
DASH_TARGET="$HA/.storage/lovelace.dashboard_house_status"
REGISTRY="$HA/.storage/lovelace_dashboards"
ASSET_DIR="$HA/www/house-status"
ASSET_TARGET="$ASSET_DIR/placeholder-floorplan.svg"
CARD_TARGET="$ASSET_DIR/lifeos-house-status-v28.js"
RELEASE_DIR="$PLATFORM/homeassistant/releases/house-status/live"
CARD_SOURCE="$RELEASE_DIR/lifeos-house-status-v28.js"
LEGACY_CARD_TARGET="$ASSET_DIR/lifeos-house-status-v27.js"
LEGACY_CARD_SOURCE="$RELEASE_DIR/lifeos-house-status-v27.js"
DOORBELL_SOURCE="$RELEASE_DIR/lifeos-house-status-doorbell.js"
DOORBELL_TARGET="$ASSET_DIR/lifeos-house-status-doorbell.js"
DOORBELL_V28_SOURCE="$RELEASE_DIR/lifeos-house-status-doorbell-v28.js"
DOORBELL_V28_TARGET="$ASSET_DIR/lifeos-house-status-doorbell-v28.js"
RESOURCES="$HA/.storage/lovelace_resources"
CONFIG="$HA/configuration.yaml"
HA_CONFIG="$HA/configuration.yaml"
SOURCE_ASSET="$RELEASE_DIR/placeholder-floorplan.svg"
DEPLOYER="$PLATFORM/homeassistant/deploy-house-status-dashboard.py"
VERIFIER="$PLATFORM/homeassistant/verify-house-status-dashboard.py"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="$HA/.storage/house-status-deploy-$STAMP"
HAD_DASH=0; HAD_ASSET=0; HAD_CARD=0; HAD_LEGACY_CARD=0; HAD_DOORBELL=0; HAD_DOORBELL_V28=0; MUTATED=0
fail(){ echo "HOUSE_STATUS_DEPLOY=FAIL"; echo "ERROR=$*"; exit 1; }
rollback(){ rc=$?; if [[ "$MUTATED" -eq 1 && "$rc" -ne 0 ]]; then echo "HOUSE_STATUS_ROLLBACK=START"; if [[ "$HAD_DASH" -eq 1 ]]; then cp -a "$BACKUP_DIR/dashboard" "$DASH_TARGET"; else rm -f "$DASH_TARGET"; fi; cp -a "$BACKUP_DIR/registry" "$REGISTRY"; cp -a "$BACKUP_DIR/resources" "$RESOURCES"; cp -a "$BACKUP_DIR/configuration.yaml" "$CONFIG"; cp -a "$BACKUP_DIR/configuration.yaml" "$HA_CONFIG"; if [[ "$HAD_ASSET" -eq 1 ]]; then cp -a "$BACKUP_DIR/asset" "$ASSET_TARGET"; else rm -f "$ASSET_TARGET"; fi; if [[ "$HAD_CARD" -eq 1 ]]; then cp -a "$BACKUP_DIR/card" "$CARD_TARGET"; else rm -f "$CARD_TARGET"; fi; if [[ "$HAD_LEGACY_CARD" -eq 1 ]]; then cp -a "$BACKUP_DIR/legacy-v27" "$LEGACY_CARD_TARGET"; else rm -f "$LEGACY_CARD_TARGET"; fi; if [[ "$HAD_DOORBELL" -eq 1 ]]; then cp -a "$BACKUP_DIR/doorbell" "$DOORBELL_TARGET"; else rm -f "$DOORBELL_TARGET"; fi; if [[ "$HAD_DOORBELL_V28" -eq 1 ]]; then cp -a "$BACKUP_DIR/doorbell-v28" "$DOORBELL_V28_TARGET"; else rm -f "$DOORBELL_V28_TARGET"; fi; docker restart homeassistant >/dev/null || true; echo "HOUSE_STATUS_ROLLBACK=COMPLETE"; fi; exit "$rc"; }
trap rollback EXIT
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "must_run_as_root"
[[ -f "$DEPLOYER" && -f "$VERIFIER" && -f "$SOURCE_ASSET" && -f "$CARD_SOURCE" && -f "$LEGACY_CARD_SOURCE" && -f "$DOORBELL_SOURCE" && -f "$DOORBELL_V28_SOURCE" ]] || fail "repository_sources_missing"
[[ -d "$HA/.storage" && -f "$REGISTRY" && -f "$RESOURCES" ]] || fail "ha_storage_missing"
python3 -m py_compile "$DEPLOYER" "$VERIFIER"
NODE_BIN=$(command -v node 2>/dev/null || find /opt/actions-runner-lifeos/externals -maxdepth 3 -type f -name node -perm -111 2>/dev/null | head -n1)
[[ -n "$NODE_BIN" ]] || fail "node_missing_for_frontend_syntax_gate"
"$NODE_BIN" --check "$CARD_SOURCE" || fail "house_status_frontend_js_syntax_invalid"
"$NODE_BIN" --check "$DOORBELL_SOURCE" || fail "house_status_doorbell_js_syntax_invalid"
"$NODE_BIN" --check "$DOORBELL_V28_SOURCE" || fail "house_status_v28_doorbell_js_syntax_invalid"
"$NODE_BIN" --check "$LEGACY_CARD_SOURCE" || fail "house_status_legacy_panel_js_syntax_invalid"
python3 -m json.tool "$PLATFORM/homeassistant/house-status-dashboard.json" >/dev/null
mkdir -p "$BACKUP_DIR" "$ASSET_DIR"; cp -a "$REGISTRY" "$BACKUP_DIR/registry"; cp -a "$RESOURCES" "$BACKUP_DIR/resources"; cp -a "$CONFIG" "$BACKUP_DIR/configuration.yaml"; cp -a "$HA_CONFIG" "$BACKUP_DIR/configuration.yaml"
if [[ -f "$DASH_TARGET" ]]; then HAD_DASH=1; cp -a "$DASH_TARGET" "$BACKUP_DIR/dashboard"; fi
if [[ -f "$ASSET_TARGET" ]]; then HAD_ASSET=1; cp -a "$ASSET_TARGET" "$BACKUP_DIR/asset"; fi
if [[ -f "$CARD_TARGET" ]]; then HAD_CARD=1; cp -a "$CARD_TARGET" "$BACKUP_DIR/card"; fi
if [[ -f "$LEGACY_CARD_TARGET" ]]; then HAD_LEGACY_CARD=1; cp -a "$LEGACY_CARD_TARGET" "$BACKUP_DIR/legacy-v27"; fi
if [[ -f "$DOORBELL_TARGET" ]]; then HAD_DOORBELL=1; cp -a "$DOORBELL_TARGET" "$BACKUP_DIR/doorbell"; fi
if [[ -f "$DOORBELL_V28_TARGET" ]]; then HAD_DOORBELL_V28=1; cp -a "$DOORBELL_V28_TARGET" "$BACKUP_DIR/doorbell-v28"; fi
install -o root -g root -m 0644 "$SOURCE_ASSET" "$ASSET_TARGET"
install -o root -g root -m 0644 "$CARD_SOURCE" "$CARD_TARGET"
install -o root -g root -m 0644 "$LEGACY_CARD_SOURCE" "$LEGACY_CARD_TARGET"
install -o root -g root -m 0644 "$DOORBELL_SOURCE" "$DOORBELL_TARGET"
install -o root -g root -m 0644 "$DOORBELL_V28_SOURCE" "$DOORBELL_V28_TARGET"
MUTATED=1
python3 - "$CONFIG" <<'PY'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); s=p.read_text()
# Replace only the production House Status panel; leave development and other panels intact.
lines=s.splitlines(True); out=[]; i=0
live_name=re.compile(r'^  - name: lifeos-house-status(?:-v[0-9]+)?\s*$')
while i<len(lines):
    if live_name.match(lines[i].rstrip('\n')):
        i+=1
        while i<len(lines) and not lines[i].startswith('  - name:') and not (lines[i] and not lines[i][0].isspace()):
            i+=1
        continue
    out.append(lines[i]); i+=1
s=''.join(out)
s=re.sub(r'(?m)^\s*- /local/house-status/lifeos-house-status(?:-card|-v[0-9]+)?\.js(?:\?[^\s]+)?\s*\n?', '', s)
panel="""  - name: lifeos-house-status-v28
    sidebar_title: House Status
    sidebar_icon: mdi:home-heart
    url_path: house-status
    module_url: /local/house-status/lifeos-house-status-v28.js?v=doorbell-shell-20261004-1
    require_admin: false
    config:
      mode: domestic
"""
match=re.search(r'(?m)^panel_custom:\s*\n',s)
if match:
    s=s[:match.end()]+panel+s[match.end():]
else:
    s=s.rstrip()+'\n\npanel_custom:\n'+panel
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
