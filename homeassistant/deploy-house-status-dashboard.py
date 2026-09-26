#!/usr/bin/env python3
import argparse, json, pathlib, shutil, sys, time

HA=pathlib.Path('/opt/stacks/homeassistant/config')
STORAGE=HA/'.storage'
SOURCE=pathlib.Path(__file__).with_name('house-status-dashboard.json')
TARGET=STORAGE/'lovelace.dashboard_house_status'
REGISTRY=STORAGE/'lovelace_dashboards'

def load(p): return json.loads(p.read_text())
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'))
def config(x): return x.get('data',{}).get('config',{})

def validate(src):
    cfg=config(src)
    views=cfg.get('views',[])
    expected=[
      ('Domestic Energy Consumption','domestic-energy-consumption'),
      ('Full Energy Flow','full-energy-flow'),
      ('Home Status','home-status'),
      ('Doorbell','doorbell')]
    got=[(v.get('title'),v.get('path')) for v in views]
    if got!=expected: raise ValueError(f'House Status views invalid: {got!r}')
    blob=canonical(cfg)
    if 'V2G' not in blob or 'charge-only' not in blob: raise ValueError('EV charge-only invariant missing')
    if 'Leave House' not in blob: raise ValueError('Home Status leave-house contract missing')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--check',action='store_true'); args=ap.parse_args()
    src=load(SOURCE); validate(src)
    if args.check:
        if not TARGET.exists(): print('DRIFT: runtime House Status dashboard absent'); return 2
        same=canonical(config(load(TARGET)))==canonical(config(src))
        print('DRIFT: none' if same else 'DRIFT: House Status dashboard differs from repository')
        return 0 if same else 2
    if not REGISTRY.exists(): raise SystemExit('HA dashboard registry missing')
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    for p in (TARGET,REGISTRY):
        if p.exists(): shutil.copy2(p,p.with_name(p.name+'.pre-repo-deploy.'+stamp+'.bak'))
    TARGET.write_text(json.dumps(src,indent=2)+'\n')
    reg=load(REGISTRY); items=reg.setdefault('data',{}).setdefault('items',[])
    items[:]=[x for x in items if x.get('url_path')!='house-status' and x.get('id')!='dashboard_house_status']
    items.append({'id':'dashboard_house_status','show_in_sidebar':True,'icon':'mdi:home-heart','title':'House Status','require_admin':False,'mode':'storage','url_path':'house-status'})
    REGISTRY.write_text(json.dumps(reg,indent=2)+'\n')
    print('DEPLOY: PASS')
    print('dashboard=/house-status')
    print('views=domestic-energy-consumption,full-energy-flow,home-status,doorbell')
    return 0

if __name__=='__main__': sys.exit(main())
