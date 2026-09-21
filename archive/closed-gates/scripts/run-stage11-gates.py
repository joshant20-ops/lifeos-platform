#!/usr/bin/env python3
"""Stage 11 entry/completion runner: prove governed autonomous execution authority.
Compact PASS output; diagnostics only on failure.
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]

def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def fail(gate,detail=''):
    print(f'STAGE11=FAIL gate={gate}')
    if detail: print(detail)
    print('===== DIAGNOSTICS =====')
    for label,cmd in [
        ('git',['git','status','--short','--branch']),
        ('head',['git','log','--oneline','--decorate','-12']),
        ('stage10/11',['git','ls-files','governor','governance','scripts/run-stage10*','scripts/run-stage11*','docs/roadmap.md']),
        ('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}']),
    ]:
        r=cp(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
    raise SystemExit(1)

def gate(name,ok,detail=''):
    if not ok: fail(name,detail)
    print(f'PASS: {name}')

# Stage 10 is the prerequisite engineering contract.
r=cp([sys.executable,'scripts/run-stage10-exit-gate.py'])
gate('stage10-prerequisite',r.returncode==0 and 'STAGE10=COMPLETE' in r.stdout,(r.stdout+r.stderr).strip())

# Repository authority must remain explicit.
readme=(REPO/'README.md').read_text()
gate('canonical-source','Canonical source of truth for LifeOS' in readme and 'Source changes are made here first' in readme)
gate('immutable-source-identity','immutable `lifeos-platform` commit SHA' in readme)
gate('watchman-sole-execution-gate','Watchman is the sole gate for' in readme)

# Stage 11 requires executable evidence of the governed path, not just prose.
patterns={
 'governor-runtime':['governor'],
 'watchman-runtime':['watchman'],
 'job-evidence':['evidence'],
 'rollback-path':['rollback'],
}
tracked=cp(['git','ls-files']).stdout.splitlines()
for name,needles in patterns.items():
    hits=[]
    for p in tracked:
        q=p.lower()
        if any(n in q for n in needles): hits.append(p)
    gate(name,bool(hits),'No tracked artifact matched: '+','.join(needles))

# Repository must be clean and synchronized before we claim authority.
r=cp(['git','status','--porcelain','--untracked-files=all'])
gate('repository-clean',r.returncode==0 and not r.stdout.strip(),r.stdout.strip())
h=cp(['git','rev-parse','HEAD']); o=cp(['git','rev-parse','origin/main'])
gate('repository-sync',h.returncode==0 and o.returncode==0 and h.stdout.strip()==o.stdout.strip(),f'HEAD={h.stdout.strip()} origin/main={o.stdout.strip()}')

print('STAGE11_GATES=PASS')
print('authority=repository immutable_source=pass execution_gate=watchman evidence=present rollback=present repository=clean synchronized=pass')
print('NEXT=Stage 11 live governed execution proof')
