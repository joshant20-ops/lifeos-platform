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
LEGACY=STORAGE/'lovelace.lifeos_control'
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
        ok=same and resource_ok
        print('DRIFT: none' if ok else 'DRIFT: dashboard or PA card resource differs from repository')
        return 0 if ok else 2
    if not REGISTRY.exists(): raise SystemExit('HA dashboard registry missing')
    if not RESOURCES.exists(): raise SystemExit('HA Lovelace resource registry missing')
    if not CARD_SOURCE.is_file(): raise SystemExit('PA card source missing')
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    for p in (TARGET,REGISTRY,RESOURCES,LEGACY,CARD_TARGET):
        if p.exists(): shutil.copy2(p,p.with_name(p.name+'.pre-repo-deploy.'+stamp+'.bak'))
    TARGET.write_text(json.dumps(src,indent=2)+'\n')
    reg=load(REGISTRY); items=reg.setdefault('data',{}).setdefault('items',[])
    # Keep exactly one LifeOS dashboard registration at /lifeos.
    items[:]=[x for x in items if x.get('url_path') not in ('lifeos','lifeos-control') and x.get('id') not in ('dashboard_lifeos','lifeos_control')]
    items.append({'id':'dashboard_lifeos','show_in_sidebar':True,'icon':'mdi:home-automation','title':'LifeOS','require_admin':False,'mode':'storage','url_path':'lifeos'})
    REGISTRY.write_text(json.dumps(reg,indent=2)+'\n')
    CARD_TARGET.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(CARD_SOURCE,CARD_TARGET)
    resources=load(RESOURCES); ritems=resources.setdefault('data',{}).setdefault('items',[])
    digest=hashlib.sha256(CARD_SOURCE.read_bytes()).hexdigest()[:12]
    ritems[:]=[x for x in ritems if x.get('id')!=CARD_ID and not str(x.get('url','')).startswith('/local/lifeos-pa-task-card.js')]
    ritems.append({'id':CARD_ID,'type':'module','url':'/local/lifeos-pa-task-card.js?v='+digest})
    RESOURCES.write_text(json.dumps(resources,indent=2)+'\n')
    if LEGACY.exists(): LEGACY.unlink()
    print('DEPLOY: PASS')
    print('dashboard=/lifeos')
    print('pa_card_resource=registered')
    print('legacy_lifeos_control=removed')
    print('tower_controls=present')
    return 0
if __name__=='__main__': sys.exit(main())
