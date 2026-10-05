#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
HA=/opt/stacks/homeassistant/config
SOURCE_DIR="$PLATFORM/homeassistant/www/house-status-dev"
TARGET_DIR="$HA/www/house-status-dev"
PROD_DIR="$HA/www/house-status"
DASH_TARGET="$HA/.storage/lovelace.dashboard_house_status"
REGISTRY="$HA/.storage/lovelace_dashboards"
RESOURCES="$HA/.storage/lovelace_resources"
CONFIG="$HA/configuration.yaml"
VERIFIER="$PLATFORM/homeassistant/verify-house-status-dev-dashboard.py"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=$(mktemp -d "/tmp/house-status-dev-deploy-$STAMP.XXXXXX")
HAD_TARGET=0
HAD_CONFIG=0
CONFIG_CHANGED=0
MUTATED=0
fail(){ echo "HOUSE_STATUS_DEV_DEPLOY=FAIL"; echo "ERROR=$*"; exit 1; }
snapshot(){
  python3 - "$@" <<'PY'
import hashlib, pathlib, sys
h=hashlib.sha256()
for raw in sys.argv[1:]:
    p=pathlib.Path(raw)
    if p.is_dir():
        paths=sorted(x for x in p.rglob('*') if x.is_file())
        for f in paths:
            h.update(str(f.relative_to(p)).encode()); h.update(b'\0'); h.update(f.read_bytes())
    elif p.is_file():
        h.update(p.name.encode()); h.update(b'\0'); h.update(p.read_bytes())
    else:
        h.update((str(p)+':missing').encode())
print(h.hexdigest())
PY
}
panel_entry(){
  python3 - "$1" "$2" <<'PY'
import pathlib, sys
lines=pathlib.Path(sys.argv[1]).read_text().splitlines()
name='  - name: '+sys.argv[2]
for i,line in enumerate(lines):
    if line==name:
        j=i+1
        while j<len(lines) and not lines[j].startswith('  - name:') and (not lines[j] or lines[j][0].isspace()):
            j+=1
        print('\n'.join(lines[i:j]))
        break
PY
}
rollback(){
  rc=$?
  if [[ "$MUTATED" -eq 1 && "$rc" -ne 0 ]]; then
    echo HOUSE_STATUS_DEV_ROLLBACK=START
    if [[ "$HAD_TARGET" -eq 1 ]]; then rm -rf "$TARGET_DIR"; cp -a "$BACKUP_DIR/dev-assets" "$TARGET_DIR"; else rm -rf "$TARGET_DIR"; fi
    if [[ "$HAD_CONFIG" -eq 1 && "$CONFIG_CHANGED" -eq 1 ]]; then cp -a "$BACKUP_DIR/configuration.yaml" "$CONFIG"; docker restart homeassistant >/dev/null || true; fi
    echo HOUSE_STATUS_DEV_ROLLBACK=COMPLETE
  fi
  rm -rf "$BACKUP_DIR"
  exit "$rc"
}
trap rollback EXIT
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail must_run_as_root
[[ -f "$SOURCE_DIR/lifeos-house-status-dev.js" && -f "$SOURCE_DIR/lifeos-house-status-doorbell.js" && -f "$SOURCE_DIR/lifeos-house-status-dev-loader.js" && -f "$SOURCE_DIR/placeholder-floorplan.svg" && -f "$VERIFIER" ]] || fail development_sources_missing
[[ -d "$HA/.storage" && -f "$DASH_TARGET" && -f "$REGISTRY" && -f "$RESOURCES" && -f "$CONFIG" ]] || fail ha_storage_missing
python3 -m py_compile "$VERIFIER"
NODE_BIN=$(command -v node 2>/dev/null || find /opt/actions-runner-lifeos/externals -maxdepth 3 -type f -name node -perm -111 2>/dev/null | head -n1)
[[ -n "$NODE_BIN" ]] || fail node_missing_for_frontend_syntax_gate
"$NODE_BIN" --check "$SOURCE_DIR/lifeos-house-status-dev.js" || fail dev_frontend_js_syntax_invalid
"$NODE_BIN" --check "$SOURCE_DIR/lifeos-house-status-doorbell.js" || fail dev_doorbell_js_syntax_invalid
"$NODE_BIN" --check "$SOURCE_DIR/lifeos-house-status-dev-loader.js" || fail dev_loader_js_syntax_invalid
python3 "$VERIFIER" --source-only
PRODUCTION_BEFORE=$(snapshot "$PROD_DIR" "$DASH_TARGET" "$REGISTRY" "$RESOURCES")
LIVE_PANEL_BEFORE=$(panel_entry "$CONFIG" lifeos-house-status-v28)
[[ -n "$LIVE_PANEL_BEFORE" ]] || fail live_panel_registration_missing
mkdir -p "$BACKUP_DIR" "$(dirname "$TARGET_DIR")"
if [[ -d "$TARGET_DIR" ]]; then HAD_TARGET=1; cp -a "$TARGET_DIR" "$BACKUP_DIR/dev-assets"; fi
cp -a "$CONFIG" "$BACKUP_DIR/configuration.yaml"
HAD_CONFIG=1
MUTATED=1
mkdir -p "$TARGET_DIR"
install -o root -g root -m 0644 "$SOURCE_DIR/lifeos-house-status-dev.js" "$TARGET_DIR/lifeos-house-status-dev.js"
install -o root -g root -m 0644 "$SOURCE_DIR/lifeos-house-status-doorbell.js" "$TARGET_DIR/lifeos-house-status-doorbell.js"
install -o root -g root -m 0644 "$SOURCE_DIR/lifeos-house-status-dev-loader.js" "$TARGET_DIR/lifeos-house-status-dev-loader.js"
install -o root -g root -m 0644 "$SOURCE_DIR/placeholder-floorplan.svg" "$TARGET_DIR/placeholder-floorplan.svg"
python3 - "$CONFIG" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text().splitlines(True)
def stanza(name):
    target='  - name: '+name
    for i,line in enumerate(lines):
        if line.rstrip('\n')==target:
            j=i+1
            while j<len(lines) and not lines[j].startswith('  - name:') and not (lines[j] and not lines[j][0].isspace()):
                j+=1
            return ''.join(lines[i:j]),i,j
    return None,None,None
live,_,_=stanza('lifeos-house-status-v28')
if not live or 'url_path: house-status\n' not in live:
    raise SystemExit('HOUSE_STATUS_DEV_CONFIG=FAIL:live_panel_not_found')
existing,i,j=stanza('lifeos-house-status-dev')
if existing:
    if 'url_path: house-status-dev\n' not in existing:
        raise SystemExit('HOUSE_STATUS_DEV_CONFIG=FAIL:dev_panel_conflict')
    old_url='module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-1'
    new_url='module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-2'
    if new_url in existing:
        print('HOUSE_STATUS_DEV_CONFIG=UNCHANGED')
    elif old_url in existing:
        for n in range(i,j):
            if old_url in lines[n]:
                lines[n]=lines[n].replace(old_url,new_url)
                break
        p.write_text(''.join(lines))
        print('HOUSE_STATUS_DEV_CONFIG=UPGRADED')
    else:
        raise SystemExit('HOUSE_STATUS_DEV_CONFIG=FAIL:dev_panel_conflict')
else:
    if any(line.strip()=='url_path: house-status-dev' for line in lines):
        raise SystemExit('HOUSE_STATUS_DEV_CONFIG=FAIL:route_owned_by_other_panel')
    header=next((i for i,line in enumerate(lines) if line.rstrip('\n')=='panel_custom:'),None)
    if header is None:
        raise SystemExit('HOUSE_STATUS_DEV_CONFIG=FAIL:panel_custom_missing')
    end=header+1
    while end<len(lines):
        line=lines[end]
        if line.strip() and not line[0].isspace() and not line.startswith('#'):
            break
        end+=1
    block=[
      '  - name: lifeos-house-status-dev\n',
      '    sidebar_title: House Status Dev\n',
      '    sidebar_icon: mdi:flask-outline\n',
      '    url_path: house-status-dev\n',
      '    module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-2\n',
      '    require_admin: true\n',
      '    config:\n',
      '      mode: domestic\n',
    ]
    lines[end:end]=block
    p.write_text(''.join(lines))
    print('HOUSE_STATUS_DEV_CONFIG=ADDED')
PY
if ! cmp -s "$CONFIG" "$BACKUP_DIR/configuration.yaml"; then CONFIG_CHANGED=1; else CONFIG_CHANGED=0; fi
docker exec homeassistant python -m homeassistant --script check_config -c /config >/dev/null
if [[ "$CONFIG_CHANGED" -eq 1 ]]; then
  docker restart homeassistant >/dev/null
  for _ in $(seq 1 60); do state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true); [[ "$state" == healthy || "$state" == running ]] && break; sleep 2; done
  state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
  [[ "$state" == healthy || "$state" == running ]] || fail homeassistant_not_healthy_after_dev_panel_registration
fi
python3 "$VERIFIER"
LIVE_PANEL_AFTER=$(panel_entry "$CONFIG" lifeos-house-status-v28)
[[ "$LIVE_PANEL_AFTER" == "$LIVE_PANEL_BEFORE" ]] || fail live_panel_registration_changed
PRODUCTION_AFTER=$(snapshot "$PROD_DIR" "$DASH_TARGET" "$REGISTRY" "$RESOURCES")
[[ "$PRODUCTION_AFTER" == "$PRODUCTION_BEFORE" ]] || fail live_dashboard_or_assets_changed
MUTATED=0
echo HOUSE_STATUS_DEV_ASSETS=/local/house-status-dev/
echo HOUSE_STATUS_DEV_PANEL=/house-status-dev
echo HOUSE_STATUS_DEV_LIVE_ISOLATION=PASS
echo HOUSE_STATUS_DEV_DEPLOY=PASS
