#!/usr/bin/env python3
import argparse, pathlib, sys
REPO=pathlib.Path(__file__).resolve().parents[1]
SOURCE=REPO/'homeassistant'/'www'/'house-status-dev'
HA=pathlib.Path('/opt/stacks/homeassistant/config')
TARGET=HA/'www'/'house-status-dev'
CONFIG=HA/'configuration.yaml'
FILES=('lifeos-house-status-dev.js','lifeos-house-status-doorbell.js','lifeos-house-status-dev-loader.js','placeholder-floorplan.svg')

def fail(msg):
    print('HOUSE_STATUS_DEV_VERIFY=FAIL:'+msg)
    raise SystemExit(1)

def stanza(text,name):
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if line=='  - name: '+name:
            j=i+1
            while j<len(lines) and not lines[j].startswith('  - name:') and (not lines[j] or lines[j][0].isspace()):
                j+=1
            return '\n'.join(lines[i:j])
    return ''

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source-only',action='store_true')
    args=ap.parse_args()
    dev=(SOURCE/'lifeos-house-status-dev.js').read_text()
    bell=(SOURCE/'lifeos-house-status-doorbell.js').read_text()
    live=(REPO/'homeassistant'/'releases'/'house-status'/'live'/'lifeos-house-status-v28.js').read_text()
    for marker in ("lifeos-house-status-dev","lifeos-house-status-dev-editor","House Status DEV","Doorbell DEV","LifeOSHouseStatusDevModules","border:2px solid #b568ff"):
        if marker not in dev: fail('development_marker_missing:'+marker)
    if 'LifeOSHouseStatusModules' in dev or 'lifeos-house-status-v28' in dev or 'lifeos-house-status-editor' in dev:
        fail('live_custom_element_or_module_namespace_reused')
    if 'LifeOSHouseStatusDevModules' not in bell or 'LifeOSHouseStatusModules' in bell:
        fail('development_doorbell_namespace_not_isolated')
    if "camera.front_door_live_view" not in bell or "camera_view:'live'" not in bell:
        fail('development_camera_config_missing')
    if dev==live: fail('development_entrypoint_matches_live_release')
    loader=(SOURCE/'lifeos-house-status-dev-loader.js').read_text()
    if "await import(bundle)" not in loader or "Date.now()" not in loader:
        fail('dev_loader_cache_bypass_missing')
    if "await import('/local/house-status-dev/lifeos-house-status-doorbell.js?dev='+Date.now())" not in dev:
        fail('dev_doorbell_cache_bypass_missing')
    if args.source_only:
        print('HOUSE_STATUS_DEV_SOURCE=PASS')
        return
    if not CONFIG.exists(): fail('ha_configuration_missing')
    cfg=CONFIG.read_text()
    live_panel=stanza(cfg,'lifeos-house-status-v28')
    dev_panel=stanza(cfg,'lifeos-house-status-dev')
    if not live_panel or 'url_path: house-status' not in live_panel: fail('live_panel_missing')
    if not dev_panel: fail('development_panel_missing')
    for marker in ('sidebar_title: House Status Dev','url_path: house-status-dev','module_url: /local/house-status-dev/lifeos-house-status-dev-loader.js?v=dev-loader-1','require_admin: true'):
        if marker not in dev_panel: fail('development_panel_config_missing:'+marker)
    for filename in FILES:
        source=SOURCE/filename
        target=TARGET/filename
        if not source.exists(): fail('dev_source_missing:'+filename)
        if not target.exists() or source.read_bytes()!=target.read_bytes(): fail('dev_runtime_asset_differs:'+filename)
    print('HOUSE_STATUS_DEV_SOURCE=PASS')
    print('HOUSE_STATUS_DEV_RUNTIME=PASS')
    print('HOUSE_STATUS_DEV_PANEL=PASS')
    print('HOUSE_STATUS_DEV_VERIFY=PASS')

if __name__=='__main__': main()
