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
def show(label,r): print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
def fail(gate,detail=''):
 print(f'STAGE10=FAIL gate={gate}')
 if detail: print(detail)
 print('===== DIAGNOSTICS =====')
 for label,cmd in [('git',['git','status','--short','--branch']),('recent commits',['git','log','--oneline','--decorate','-8']),('stage10 branch diff',['git','diff','--stat',f'HEAD..origin/{BRANCH}']),('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}'])]: show(label,cp(cmd))
 raise SystemExit(1)
def gate(name,cmd,needle=None):
 r=cp(cmd)
 if r.returncode or (needle and needle not in r.stdout): fail(name,(r.stdout+r.stderr).strip())
 print(f'PASS: {name}')

r=cp(['git','fetch','origin',BRANCH])
if r.returncode: fail('fetch-stage10',(r.stdout+r.stderr).strip())
for f in FILES:
 r=cp(['git','show',f'origin/{BRANCH}:{f}'])
 if r.returncode: fail('contract-source',f'{f}\n{r.stderr}')
 p=REPO/f; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(r.stdout)
print('PASS: contract-source')

gate('contract-validator',[sys.executable,'scripts/validate-engineering-work-contract.py','governor/contracts/examples/stage10-smoke.json'],'CONTRACT_VALIDATION=PASS')
gate('contract-tests',[sys.executable,'-m','unittest','tests.test_engineering_work_contract'])
try:
 s=json.loads((REPO/FILES[0]).read_text()); props=s.get('properties',{}); req=set(s.get('required',[])); needed={'work_id','issue','objective','risk_class','state','plan','tests','deployment','runtime_verification','evidence'}
 if not needed <= set(props) or not needed <= req: raise ValueError('schema missing Stage 10 required primitives')
except Exception as e: fail('schema-integrity',repr(e))
print('PASS: schema-integrity')
gate('ha-runtime',[sys.executable,'homeassistant/verify-lifeos-dashboard.py'],'LIFEOS_HA_GATE=PASS')

# Porcelain collapses a wholly-untracked directory to "?? dir/". Ask Git for all
# untracked files explicitly, then verify every changed path is one we materialised.
r=cp(['git','status','--porcelain','--untracked-files=all'])
allowed=set(FILES); unexpected=[]; seen=set()
for line in r.stdout.splitlines():
 path=line[3:].split(' -> ')[-1]; seen.add(path)
 if path not in allowed: unexpected.append(line)
if unexpected: fail('working-tree-safety','unexpected changes:\n'+'\n'.join(unexpected))
missing=allowed-seen
if missing:
 # Already tracked artifacts are fine only when byte-identical to the Stage 10 branch.
 for f in sorted(missing):
  local=(REPO/f).read_text(); src=cp(['git','show',f'origin/{BRANCH}:{f}'])
  if src.returncode or local!=src.stdout: fail('working-tree-safety',f'artifact mismatch: {f}')
print('PASS: working-tree-safety')

print('STAGE10_GATES=PASS')
print('contract=valid tests=pass fail_closed=pass schema=pass runtime=pass safety=pass')
print('NEXT=Stage 10 artifacts are validated and ready for repository integration')
