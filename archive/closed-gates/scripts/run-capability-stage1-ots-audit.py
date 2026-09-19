#!/usr/bin/env python3
"""Capability Stage 1: OTS rationalisation and custom-code purge audit.

One big gated runner. Compact on PASS; detailed diagnostics on FAIL.
Read-only with respect to repository/runtime; writes a local JSON report only.
"""
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
POLICY=REPO/'governor/capability-roadmap/stage1-ots-rationalisation.json'
REPORT=Path.home()/'.local/state/lifeos/capability-stage1-ots-report.json'

def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def fail(gate,detail=''):
    print(f'CAPABILITY_STAGE1=FAIL gate={gate}')
    if detail: print(detail)
    print('===== DIAGNOSTICS =====')
    for label,cmd in [
        ('git',['git','status','--short','--branch']),
        ('head',['git','log','--oneline','--decorate','-12']),
        ('containers',['docker','ps','--format','{{.Names}}\t{{.Image}}\t{{.Status}}']),
        ('lifeos-units',['systemctl','list-unit-files','lifeos-*','--no-pager']),
    ]:
        r=cp(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
    raise SystemExit(1)
def gate(name,cond,detail=''):
    if not cond: fail(name,detail)
    print(f'PASS: {name}')

def tracked():
    r=cp(['git','ls-files'])
    if r.returncode: fail('tracked-files',r.stderr.strip())
    return [x for x in r.stdout.splitlines() if x]

# 0 — completed foundation roadmap prerequisite.
r=cp([sys.executable,'scripts/run-stage12-complete.py'])
gate('foundation-prerequisite',r.returncode==0 and 'ROADMAP=12/12 COMPLETE' in r.stdout,(r.stdout+r.stderr).strip())

# 1 — explicit OTS-first policy.
try: p=json.loads(POLICY.read_text())
except Exception as e: fail('policy',repr(e))
gate('ots-first-policy',p.get('capability_stage')==1 and p.get('auto_delete') is False)

files=tracked()

# 2 — inventory bespoke executable/config surface in canonical repository.
code_ext={'.py','.sh','.js','.ts','.go','.rs','.java','.rb','.php'}
custom=[]
for f in files:
    path=Path(f)
    if path.suffix.lower() in code_ext or f.startswith(('scripts/','homelab/live/usr/local/','homeassistant/')):
        custom.append(f)
gate('custom-inventory',len(custom)>0,'No candidate custom surface discovered')

# 3 — inventory known OTS platform components from live containers.
r=cp(['docker','ps','--format','{{.Names}}|{{.Image}}'])
gate('docker-inventory',r.returncode==0,r.stderr.strip())
containers=[]
for line in r.stdout.splitlines():
    if '|' in line:
        name,image=line.split('|',1); containers.append({'name':name,'image':image})
ots_markers=['home-assistant','semaphore','paperless','mosquitto','uptime-kuma','vaultwarden','adguard','nginx-proxy-manager','zwave','matter','predbat','open-webui','postgres','redis','qbittorrent']
ots_live=[c for c in containers if any(m in (c['name']+' '+c['image']).lower() for m in ots_markers)]
gate('ots-runtime-inventory',len(ots_live)>=5,f'OTS runtime count={len(ots_live)}')

# 4 — classify repository custom surface conservatively. No deletion without proof.
classifications=[]
for f in custom:
    low=f.lower()
    if any(x in low for x in ('stage10','stage11','stage12','rollback','recovery','verify-lifeos-dashboard','deploy-lifeos-dashboard')):
        cls='KEEP_THIN_GLUE'; reason='governance/runtime verification boundary'
    elif any(x in low for x in ('legacy','retire','migration','shadow-proof','rehearsal')):
        cls='RETIRE_OBSOLETE'; reason='migration/proof artifact candidate; requires reference check before deletion'
    elif low.startswith('homeassistant/'):
        cls='KEEP_THIN_GLUE'; reason='repository-native HA source/deployment adapter'
    elif low.startswith('scripts/'):
        cls='REVIEW_UNIQUE'; reason='custom orchestration; compare against Semaphore/Ansible/GitHub Actions/HA native capability'
    else:
        cls='REVIEW_UNIQUE'; reason='custom executable surface requires responsibility classification'
    classifications.append({'path':f,'classification':cls,'reason':reason})

counts={}
for x in classifications: counts[x['classification']]=counts.get(x['classification'],0)+1
gate('classification-complete',sum(counts.values())==len(custom))

# 5 — identify active custom systemd units that deserve OTS/replacement review.
r=cp(['systemctl','list-unit-files','lifeos-*','--no-legend','--no-pager'])
units=[]
if r.returncode==0:
    for line in r.stdout.splitlines():
        parts=line.split()
        if parts: units.append({'unit':parts[0],'state':parts[1] if len(parts)>1 else 'unknown'})
print(f'PASS: custom-systemd-inventory units={len(units)}')

# 6 — verify known retired dispatcher/worker units are not accidentally back.
retired=['lifeos-engineer-worker.timer','lifeos-engineer-dispatcher.timer','lifeos-backlog-runner.timer']
active_bad=[]
for u in retired:
    rr=cp(['systemctl','is-active',u])
    if rr.stdout.strip()=='active': active_bad.append(u)
gate('retired-runtime-stays-retired',not active_bad,'active retired units: '+','.join(active_bad))

# 7 — repository cleanliness/sync: audit itself must not mutate canonical source.
r=cp(['git','status','--porcelain','--untracked-files=all'])
gate('repository-clean',r.returncode==0 and not r.stdout.strip(),r.stdout.strip())
h=cp(['git','rev-parse','HEAD']); o=cp(['git','rev-parse','origin/main'])
gate('repository-sync',h.returncode==0 and o.returncode==0 and h.stdout.strip()==o.stdout.strip(),f'HEAD={h.stdout.strip()} origin/main={o.stdout.strip()}')

# 8 — durable local report for follow-up replacement/retirement gates.
REPORT.parent.mkdir(parents=True,exist_ok=True)
report={
    'schema_version':1,
    'capability_stage':1,
    'generated_at_epoch':int(time.time()),
    'principle':p['principle'],
    'repository_head':h.stdout.strip(),
    'custom_surface_count':len(custom),
    'classification_counts':counts,
    'custom_systemd_units':units,
    'live_ots_components':ots_live,
    'items':classifications,
    'auto_delete':False,
    'next_policy':'Replace/retire only after unique responsibility and rollback proof.'
}
REPORT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print('PASS: durable-report')

# 9 — final non-mutation proof.
r=cp(['git','status','--porcelain','--untracked-files=all'])
gate('final-non-mutating',r.returncode==0 and not r.stdout.strip(),r.stdout.strip())

print('CAPABILITY_STAGE1_AUDIT=PASS')
print(f'custom_surface={len(custom)} ots_live={len(ots_live)} systemd_units={len(units)}')
print('classification='+' '.join(f'{k}:{v}' for k,v in sorted(counts.items())))
print(f'REPORT={REPORT}')
if counts.get('REVIEW_UNIQUE',0) or counts.get('RETIRE_OBSOLETE',0):
    print('CAPABILITY_STAGE1=IN_PROGRESS')
    print('NEXT=build gated OTS replacement/retirement batches from this report')
else:
    print('CAPABILITY_STAGE1=COMPLETE')
    print('NEXT=Capability Stage 2')
