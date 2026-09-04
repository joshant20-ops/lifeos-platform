#!/usr/bin/env python3
"""Stage 10 gated runner: compact PASS, comprehensive diagnostics on FAIL."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
BRANCH='stage10-engineering-contract'
FILES=[
 'governor/contracts/engineering-work.schema.json',
 'governor/contracts/examples/stage10-smoke.json',
 'scripts/validate-engineering-work-contract.py',
 'tests/test_engineering_work_contract.py',
]

def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def show(label,r):
 print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
def fail(gate,detail=''):
 print(f'STAGE10=FAIL gate={gate}')
 if detail: print(detail)
 print('===== DIAGNOSTICS =====')
 for label,cmd in [
  ('git',['git','status','--short','--branch']),
  ('recent commits',['git','log','--oneline','--decorate','-8']),
  ('stage10 branch diff',['git','diff','--stat',f'HEAD..origin/{BRANCH}']),
  ('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}']),
 ]: show(label,cp(cmd))
 raise SystemExit(1)

def gate(name,cmd,needle=None):
 r=cp(cmd)
 if r.returncode or (needle and needle not in r.stdout):
  fail(name,(r.stdout+r.stderr).strip())
 print(f'PASS: {name}')

# Gate 1: source contract artifacts are imported from the reviewed Stage 10 branch.
r=cp(['git','fetch','origin',BRANCH])
if r.returncode: fail('fetch-stage10',(r.stdout+r.stderr).strip())
for f in FILES:
 r=cp(['git','show',f'origin/{BRANCH}:{f}'])
 if r.returncode: fail('contract-source',f'{f}\n{r.stderr}')
 p=REPO/f; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(r.stdout)
print('PASS: contract-source')

# Gate 2: validator accepts canonical bounded engineering contract.
gate('contract-validator',[sys.executable,'scripts/validate-engineering-work-contract.py','governor/contracts/examples/stage10-smoke.json'],'CONTRACT_VALIDATION=PASS')

# Gate 3: positive + fail-closed negative tests.
gate('contract-tests',[sys.executable,'-m','unittest','tests.test_engineering_work_contract'])

# Gate 4: schema itself parses and carries the required Stage 10 primitives.
try:
 s=json.loads((REPO/FILES[0]).read_text())
 props=s.get('properties',{}); req=set(s.get('required',[]))
 needed={'work_id','issue','objective','risk_class','state','plan','tests','deployment','runtime_verification','evidence'}
 if not needed <= set(props) or not needed <= req: raise ValueError('schema missing Stage 10 required primitives')
except Exception as e: fail('schema-integrity',repr(e))
print('PASS: schema-integrity')

# Gate 5: existing HA runtime/deployment gate remains green after Stage 10 integration.
gate('ha-runtime',[sys.executable,'homeassistant/verify-lifeos-dashboard.py'],'LIFEOS_HA_GATE=PASS')

# Gate 6: repository must contain no unstaged changes except the four artifacts this runner intentionally materialises.
r=cp(['git','status','--porcelain'])
allowed=set(FILES); unexpected=[]
for line in r.stdout.splitlines():
 path=line[3:].split(' -> ')[-1]
 if path not in allowed: unexpected.append(line)
if unexpected: fail('working-tree-safety','unexpected changes:\n'+'\n'.join(unexpected))
print('PASS: working-tree-safety')

print('STAGE10_GATES=PASS')
print('contract=valid tests=pass fail_closed=pass schema=pass runtime=pass')
print('NEXT=commit the four materialised Stage 10 contract artifacts to main')
