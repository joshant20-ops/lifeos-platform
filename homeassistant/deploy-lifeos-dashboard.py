#!/usr/bin/env python3
import argparse, hashlib, json, pathlib, shutil, sys, time

HA=pathlib.Path('/opt/stacks/homeassistant/config')
STORAGE=HA/'.storage'
SOURCE=pathlib.Path(__file__).with_name('lifeos-dashboard.json')
TARGET=STORAGE/'lovelace.dashboard_lifeos'
REGISTRY=STORAGE/'lovelace_dashboards'
RESOURCES=STORAGE/'lovelace_resources'
CARD_SOURCE=pathlib.Path(__file__).with_name('www')/'lifeos-pa-task-card.js'
CARD_TARGET=HA/'www'/'lifeos-pa-task-card.js'
CARD_ID='lifeos-pa-task-card'
CONTROL=STORAGE/'lovelace.lifeos_control'
CONTROL_ID='lifeos_control'
CONTROL_PATH='lifeos-control'
REQUIRED={'sensor.tower_pc_tower_status','binary_sensor.tower_pc_tower_accessible','switch.tower_pc_tower_power'}

def load(p): return json.loads(p.read_text())
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'))
def validate(src):
    cfg=src.get('data',{}).get('config',{})
    views=cfg.get('views',[])
    if not views or views[0].get('path')!='overview': raise ValueError('Overview view missing')
    entities=set()
    for v in views:
      for c in v.get('cards',[]):
       for e in c.get('entities',[]): entities.add(e if isinstance(e,str) else e.get('entity'))
    missing=REQUIRED-entities
    if missing: raise ValueError('Tower controls missing: '+', '.join(sorted(missing)))
    if not any(c.get('type')=='custom:lifeos-pa-task-card' for c in views[0].get('cards',[])): raise ValueError('PA action card missing from Overview')

def normalized_dashboard(x): return x.get('data',{}).get('config',{})

def control_registration(items):
    matches=[x for x in items if isinstance(x,dict) and (x.get('id')==CONTROL_ID or x.get('url_path')==CONTROL_PATH)]
    if len(matches)>1: raise ValueError('Duplicate LifeOS Control dashboard registrations')
    if matches:
        item=matches[0]
        if item.get('id')!=CONTROL_ID or item.get('url_path')!=CONTROL_PATH or item.get('mode')!='storage':
            raise ValueError('LifeOS Control dashboard registration is inconsistent')
        return item
    return None

def reconcile_dashboard_registry(items):
    if not isinstance(items,list): raise ValueError('Dashboard registry items must be a list')
    control=control_registration(items)
    unrelated=[
        x for x in items
        if not (isinstance(x,dict) and (
            x.get('id') in ('dashboard_lifeos',CONTROL_ID) or
            x.get('url_path') in ('lifeos',CONTROL_PATH)
        ))
    ]
    lifeos={'id':'dashboard_lifeos','show_in_sidebar':True,'icon':'mdi:home-automation','title':'LifeOS','require_admin':False,'mode':'storage','url_path':'lifeos'}
    return unrelated+[lifeos]+([control] if control else [])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--check',action='store_true'); args=ap.parse_args()
    src=load(SOURCE); validate(src)
    if args.check:
        if not TARGET.exists(): print('DRIFT: runtime LifeOS dashboard absent'); return 2
        same=canonical(normalized_dashboard(load(TARGET)))==canonical(normalized_dashboard(src))
        resource_ok=False
        try:
            resources=load(RESOURCES).get('data',{}).get('items',[])
            digest=hashlib.sha256(CARD_SOURCE.read_bytes()).hexdigest()[:12]
            expected='/local/lifeos-pa-task-card.js?v='+digest
            resource_ok=any(x.get('id')==CARD_ID and x.get('type')=='module' and x.get('url')==expected for x in resources) and CARD_TARGET.read_bytes()==CARD_SOURCE.read_bytes()
        except Exception:
            resource_ok=False
        registry_ok=False
        try:
            items=load(REGISTRY).get('data',{}).get('items',[])
            personal=[x for x in items if isinstance(x,dict) and (x.get('id')=='dashboard_lifeos' or x.get('url_path')=='lifeos')]
            control=control_registration(items)
            registry_ok=len(personal)==1 and personal[0].get('id')=='dashboard_lifeos' and personal[0].get('url_path')=='lifeos' and personal[0].get('mode')=='storage'
            registry_ok=registry_ok and (control is None or CONTROL.is_file())
        except Exception:
            registry_ok=False
        ok=same and resource_ok and registry_ok
        print('DRIFT: none' if ok else 'DRIFT: dashboard, registration, or PA card resource differs from repository')
        print('CONTROL_DASHBOARD=' + ('registered_and_preserved' if registry_ok and control else 'absent' if registry_ok else 'invalid'))
        return 0 if ok else 2
    if not REGISTRY.exists(): raise SystemExit('HA dashboard registry missing')
    if not RESOURCES.exists(): raise SystemExit('HA Lovelace resource registry missing')
    if not CARD_SOURCE.is_file(): raise SystemExit('PA card source missing')
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    for p in (TARGET,REGISTRY,RESOURCES,CONTROL,CARD_TARGET):
        if p.exists(): shutil.copy2(p,p.with_name(p.name+'.pre-repo-deploy.'+stamp+'.bak'))
    TARGET.write_text(json.dumps(src,indent=2)+'\n')
    reg=load(REGISTRY); items=reg.setdefault('data',{}).setdefault('items',[])
    # LifeOS owns its personal dashboard registration; an independently-owned
    # LifeOS Control registration and storage file remain intact.
    if control_registration(items) is not None and not CONTROL.is_file():
        raise SystemExit('LifeOS Control is registered but its storage file is missing')
    reg['data']['items']=reconcile_dashboard_registry(items)
    REGISTRY.write_text(json.dumps(reg,indent=2)+'\n')
    CARD_TARGET.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(CARD_SOURCE,CARD_TARGET)
    resources=load(RESOURCES); ritems=resources.setdefault('data',{}).setdefault('items',[])
    digest=hashlib.sha256(CARD_SOURCE.read_bytes()).hexdigest()[:12]
    ritems[:]=[x for x in ritems if x.get('id')!=CARD_ID and not str(x.get('url','')).startswith('/local/lifeos-pa-task-card.js')]
    ritems.append({'id':CARD_ID,'type':'module','url':'/local/lifeos-pa-task-card.js?v='+digest})
    RESOURCES.write_text(json.dumps(resources,indent=2)+'\n')
    print('DEPLOY: PASS')
    print('dashboard=/lifeos')
    print('pa_card_resource=registered')
    print('control_dashboard='+('preserved' if control_registration(reg['data']['items']) else 'absent'))
    print('tower_controls=present')
    return 0
if __name__=='__main__': sys.exit(main())
