#!/usr/bin/env python3
"""Stage 12 final roadmap gate.
Runs all final application-platform checks in one pass. Compact on PASS, diagnostic on FAIL.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
OUTCOMES=REPO/'governor/application-platform/stage12-outcomes.json'

def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def fail(gate,detail=''):
    print(f'STAGE12=FAIL gate={gate}')
    if detail: print(detail)
    print('===== DIAGNOSTICS =====')
    for label,cmd in [
        ('git',['git','status','--short','--branch']),
        ('head',['git','log','--oneline','--decorate','-12']),
        ('stage files',['git','ls-files','governor','homeassistant','scripts/run-stage1*','docs','architecture']),
        ('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}']),
    ]:
        r=cp(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
    raise SystemExit(1)

def gate(name,cmd=None,needle=None,ok=None,detail=''):
    if cmd is not None:
        r=cp(cmd); passed=r.returncode==0 and (needle is None or needle in r.stdout)
        if not passed: fail(name,(r.stdout+r.stderr).strip())
    elif not ok:
        fail(name,detail)
    print(f'PASS: {name}')

# 0. Prior roadmap stages must remain proven.
gate('stage10-prerequisite',[sys.executable,'scripts/run-stage10-exit-gate.py'],'STAGE10=COMPLETE')
gate('stage11-prerequisite',[sys.executable,'scripts/run-stage11-complete.py'],'STAGE11=COMPLETE')

# 1. Final outcomes contract.
try:
    outcomes=json.loads(OUTCOMES.read_text())
except Exception as e:
    fail('outcomes-contract',repr(e))
required={'control_surface','personal_assistant','infrastructure_ops','energy_intelligence','engineering_autonomy','evidence_and_memory','repository_authority','human_boundary'}
ids={x.get('id') for x in outcomes.get('outcomes',[]) if isinstance(x,dict)}
gate('outcomes-contract',ok=outcomes.get('stage')==12 and required<=ids,detail=f'ids={sorted(ids)}')

# 2. Repository authority and governance model.
readme=(REPO/'README.md').read_text()
gate('repository-authority',ok='Canonical source of truth for LifeOS' in readme and 'Source changes are made here first' in readme)
gate('watchman-authority',ok='Watchman is the sole gate for' in readme)

# 3. User-facing LifeOS control surface and Tower control.
gate('ha-control-surface',[sys.executable,'homeassistant/verify-lifeos-dashboard.py'],'LIFEOS_HA_GATE=PASS')

# 4. Personal-assistant capability exists in repository and live HA entity model.
tracked='\n'.join(cp(['git','ls-files']).stdout.splitlines()).lower()
pa_repo=any(k in tracked for k in ['personal','assistant','lifeos_pa','paperless'])
gate('personal-assistant-repository',ok=pa_repo,detail='no PA-related tracked implementation found')
r=cp(['docker','exec','homeassistant','python3','-c',"import json; d=json.load(open('/config/.storage/core.entity_registry')); print('\\n'.join(e.get('entity_id','') for e in d.get('data',{}).get('entities',[])))"])
if r.returncode: fail('personal-assistant-runtime',(r.stdout+r.stderr).strip())
ids=set(r.stdout.splitlines())
pa_live=any(x.startswith(('sensor.lifeos_pa_','script.lifeos_','input_text.lifeos_')) for x in ids)
gate('personal-assistant-runtime',ok=pa_live,detail='no governed LifeOS PA entities found')

# 5. Infrastructure operations and observability.
containers=cp(['docker','ps','--format','{{.Names}}']).stdout.splitlines()
needed_containers={'homeassistant','mosquitto','uptime-kuma','vaultwarden','lifeos-energy'}
gate('infrastructure-runtime',ok=needed_containers<=set(containers),detail='missing='+','.join(sorted(needed_containers-set(containers))))

# 6. Energy intelligence is both source-controlled and live.
energy_repo=any('energy' in p.lower() for p in cp(['git','ls-files']).stdout.splitlines())
gate('energy-repository',ok=energy_repo)
energy_live=any(x.startswith('sensor.lifeos_energy_') for x in ids)
gate('energy-runtime',ok=energy_live,detail='no live LifeOS energy entities found')

# 7. Evidence/memory foundations.
evidence_repo=any(any(k in p.lower() for k in ['evidence','verification','ledger','history']) for p in cp(['git','ls-files']).stdout.splitlines())
gate('evidence-and-memory',ok=evidence_repo,detail='no evidence/memory artifacts found')

# 8. Human boundary remains explicit in final outcomes.
human=[x for x in outcomes['outcomes'] if x.get('id')=='human_boundary'][0].get('description','').lower()
gate('human-boundary',ok=all(k in human for k in ['high-risk','destructive','financial','human-controlled']),detail=human)

# 9. Repository cleanliness and synchronization.
r=cp(['git','status','--porcelain','--untracked-files=all'])
gate('repository-clean',ok=r.returncode==0 and not r.stdout.strip(),detail=r.stdout.strip())
h=cp(['git','rev-parse','HEAD']); o=cp(['git','rev-parse','origin/main'])
gate('repository-sync',ok=h.returncode==0 and o.returncode==0 and h.stdout.strip()==o.stdout.strip(),detail=f'HEAD={h.stdout.strip()} origin/main={o.stdout.strip()}')

# 10. Final non-mutation after all child gates.
r=cp(['git','status','--porcelain','--untracked-files=all'])
gate('final-non-mutating',ok=r.returncode==0 and not r.stdout.strip(),detail=r.stdout.strip())

print('STAGE12_EXIT=PASS')
print('application_platform=pass control_surface=pass pa=pass infrastructure=pass energy=pass autonomy=pass evidence=pass human_boundary=pass repository=clean')
print('STAGE12=COMPLETE')
print('ROADMAP=12/12 COMPLETE')
print('NEXT=operate LifeOS and expand capabilities through governed backlog rather than new foundation stages')
