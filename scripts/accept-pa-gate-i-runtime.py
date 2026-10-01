#!/usr/bin/env python3
"""Sanitized final Gate I acceptance on the canonical lifeos-pi5 runtime."""
from __future__ import annotations
import hashlib, json, os, pathlib, re, subprocess, sys, time

REPO=pathlib.Path('/home/joshan/lifeos-platform')
HA=pathlib.Path('/opt/stacks/homeassistant/config')
STORAGE=HA/'.storage'
PERSISTED=pathlib.Path('/home/joshan/automation/state/lifeos_personal_tasks.json')
PROJECTION=HA/'www/lifeos_tasks.json'
RECONCILER=pathlib.Path('/home/joshan/automation/lifeos_task_reconciler.py')
SOURCE=REPO/'homelab/live/home/joshan/automation/lifeos_task_reconciler.py'
PUBLISHER='homelab/live/home/joshan/automation/lifeos_task_reconciler.py'
checks=[]

def run(args, timeout=30):
    return subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=False)

def require(name, ok):
    ok=bool(ok)
    checks.append((name,ok))
    print(name+'='+('PASS' if ok else 'FAIL'))
    if not ok: raise RuntimeError(name)

def read_json(path):
    return json.loads(path.read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ''

def main():
    head=run(['git','-C',str(REPO),'rev-parse','HEAD'])
    origin=run(['git','-C',str(REPO),'rev-parse','origin/main'])
    dirty=run(['git','-C',str(REPO),'status','--porcelain','--untracked-files=all'])
    require('CANONICAL_CLEAN_CHECKOUT',head.returncode==0 and origin.returncode==0 and head.stdout.strip()==origin.stdout.strip() and not dirty.stdout.strip())

    unit_files=run(['systemctl','list-unit-files','--no-legend','--no-pager'])
    loaded_services=run(['systemctl','list-units','--all','--type=service','--no-legend','--no-pager'])
    loaded_timers=run(['systemctl','list-units','--all','--type=timer','--no-legend','--no-pager'])
    unit_names={x.split()[0] for x in unit_files.stdout.splitlines() if x.split()}
    service_names={x.split()[0] for x in loaded_services.stdout.splitlines() if x.split()}
    timer_names={x.split()[0] for x in loaded_timers.stdout.splitlines() if x.split()}
    pattern=re.compile(r'(?i)(?=.*(?:task|personal))(?=.*reconcil)')
    services=sorted(x for x in unit_names|service_names if x.endswith('.service') and pattern.search(x))
    timers=sorted(x for x in unit_names|timer_names if x.endswith('.timer') and pattern.search(x))
    require('SINGLE_RECONCILER_SERVICE',services==['lifeos-task-reconciler.service'])
    require('SINGLE_RECONCILER_TIMER',timers==['lifeos-task-reconciler.timer'])
    svc=run(['systemctl','show','lifeos-task-reconciler.service','-p','Result','-p','ExecMainStatus'])
    svcp=dict(x.split('=',1) for x in svc.stdout.splitlines() if '=' in x)
    timer=run(['systemctl','show','lifeos-task-reconciler.timer','-p','ActiveState','-p','UnitFileState'])
    timerp=dict(x.split('=',1) for x in timer.stdout.splitlines() if '=' in x)
    require('RECONCILER_LAST_RUN_SUCCESS',svcp.get('Result')=='success' and svcp.get('ExecMainStatus')=='0')
    require('RECONCILER_TIMER_ENABLED_AND_ACTIVE',timerp.get('ActiveState')=='active' and timerp.get('UnitFileState')=='enabled')

    running=[]
    for proc in pathlib.Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            cmd=(proc/'cmdline').read_bytes().replace(bytes([0]),b' ').decode(errors='ignore')
            if 'lifeos_task_reconciler.py' in cmd and int(proc.name)!=os.getpid(): running.append(proc.name)
        except (OSError,ValueError): pass
    require('NO_COMPETING_RECONCILER_PROCESS',len(running)==0)
    py_sources=[]
    for path in REPO.rglob('*.py'):
        if 'archive' in path.parts: continue
        if 'www/lifeos_tasks.json' in path.read_text(errors='ignore'):
            py_sources.append(str(path.relative_to(REPO)))
    require('SINGLE_TASK_VIEW_PUBLISHER',py_sources==[PUBLISHER])
    require('INSTALLED_RECONCILER_MATCHES_SOURCE',bool(digest(SOURCE)) and digest(SOURCE)==digest(RECONCILER))

    state=read_json(PERSISTED); published=read_json(PROJECTION); now=time.time()
    require('PERSISTED_AND_HA_PROJECTION_EQUAL',state==published)
    require('TASK_VIEW_SCHEMA_VALID',state.get('schema')=='lifeos_tasks_v3')
    require('TASK_VIEW_FRESH',0<=now-float(state.get('generated_time') or 0)<=7*3600)
    require('TASK_VIEW_ZERO_ERRORS',int(state.get('errors',-1))==0)

    health=run(['docker','inspect','-f','{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}','homeassistant'])
    require('HOME_ASSISTANT_HEALTHY',health.returncode==0 and health.stdout.strip().lower() in {'healthy','running'})

    registry=read_json(STORAGE/'lovelace_dashboards').get('data',{}).get('items',[])
    ids={}
    for item in registry:
        if not isinstance(item,dict): continue
        path=item.get('url_path')
        if path: ids.setdefault(path,[]).append(item)
    expected=(('dashboard-homelab','dashboard_homelab'),('lifeos','dashboard_lifeos'),('lifeos-control','lifeos_control'))
    for url_path,dashboard_id in expected:
        found=ids.get(url_path,[])
        require('DASHBOARD_'+dashboard_id.upper()+'_SINGLE_REGISTRATION',len(found)==1 and found[0].get('id')==dashboard_id and found[0].get('mode')=='storage')
        require('DASHBOARD_'+dashboard_id.upper()+'_UNIQUE_PATH',len(found)==1)
    require('DASHBOARD_URL_PATHS_UNIQUE',all(len(items)==1 for items in ids.values()))

    # Home Assistant's canonical Homelab V2 uses Sections; count both that schema
    # and legacy cards to avoid treating a nonempty Sections view as empty.
    homelab=read_json(STORAGE/'lovelace.dashboard_homelab').get('data',{}).get('config',{}).get('views',[])
    require('HOMELAB_V2_VIEW_PATHS',[v.get('path') for v in homelab]==['overview','network','tower'])
    section_cards=sum(len(section.get('cards',[])) for view in homelab for section in (view.get('sections') or []) if isinstance(section,dict))
    old_cards=sum(len(view.get('cards',[])) for view in homelab if isinstance(view.get('cards'),list))
    require('HOMELAB_V2_RENDERABLE_SECTIONS',all(v.get('type')=='sections' and v.get('sections') for v in homelab) and section_cards+old_cards>0)

    source=read_json(REPO/'homeassistant/lifeos-dashboard.json')
    personal=read_json(STORAGE/'lovelace.dashboard_lifeos').get('data',{}).get('config',{}).get('views',[])
    require('LIFEOS_PERSONAL_DASHBOARD_PATHS',[v.get('path') for v in personal]==[v.get('path') for v in source['data']['config']['views']])
    require('LIFEOS_PERSONAL_VIEWS_RENDERABLE',all(isinstance(v.get('cards'),list) and v['cards'] for v in personal))
    check=run(['python3',str(REPO/'homeassistant/deploy-lifeos-dashboard.py'),'--check'])
    require('LIFEOS_DASHBOARD_SOURCE_DRIFT_FREE',check.returncode==0 and 'DRIFT: none' in check.stdout)
    verify=run(['python3',str(REPO/'homeassistant/verify-lifeos-dashboard.py')],timeout=90)
    require('LIFEOS_DASHBOARD_FUNCTIONAL_VERIFIER',verify.returncode==0 and 'LIFEOS_HA_GATE=PASS' in verify.stdout)

    control_path=STORAGE/'lovelace.lifeos_control'
    control=read_json(control_path).get('data',{}).get('config',{}).get('views',[])
    z97=[v for v in control if v.get('path')=='z97']
    require('LIFEOS_CONTROL_STORAGE_AND_Z97',len(z97)==1 and z97[0].get('type')=='masonry' and len(z97[0].get('cards',[]))>=10)
    history=[c for c in z97[0].get('cards',[]) if c.get('type')=='history-graph'] if z97 else []
    disks=[c for c in history if str(c.get('title') or '').startswith('Disk ')]
    require('LIFEOS_CONTROL_Z97_HISTORY',len(history)>=7 and len(disks)>=2)

    workflows=REPO/'.github/workflows'
    active='\n'.join(p.read_text(errors='ignore') for p in workflows.glob('*.yml'))
    require('SUPERSEDED_DASHBOARD_WORKFLOWS_RETIRED','three-dashboard-role-deploy.yml' not in [p.name for p in workflows.glob('*.yml')] and 'homelab-dashboard-deploy.yml' not in [p.name for p in workflows.glob('*.yml')])
    require('ACTIVE_WORKFLOWS_USE_SINGLE_HOMELAB_OWNER','deploy-homelab-default-view.py' not in active and active.count('deploy-homelab-dashboard-v2.py')==1)
    require('ACTIVE_WORKFLOWS_NO_ROLE_REDEPLOYER','deploy-three-dashboard-roles.py' not in active)

    print('GATE_I_RUNTIME_AUDIT=PASS')

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        # Exceptions are reduced to a fixed stage token: no runtime or PA content.
        print('GATE_I_RUNTIME_AUDIT=FAIL')
        print('GATE_I_FAILURE_STAGE='+str(exc)[:80].replace(' ','_'))
        raise SystemExit(1)
