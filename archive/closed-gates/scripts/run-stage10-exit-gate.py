#!/usr/bin/env python3
"""Consolidated Stage 10 completion/exit gate. Compact PASS; full diagnostics on failure."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def fail(gate,detail=''):
 print(f'STAGE10_EXIT=FAIL gate={gate}')
 if detail: print(detail)
 print('===== DIAGNOSTICS =====')
 for label,cmd in [('git',['git','status','--short','--branch']),('head',['git','log','--oneline','--decorate','-10']),('stage10 files',['git','ls-files','governor/contracts','scripts/run-stage10*','scripts/validate-engineering-work-contract.py','tests/test_engineering_work_contract.py']),('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}'])]:
  r=cp(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
 raise SystemExit(1)
def run_gate(name,path,needle):
 r=cp([sys.executable,path])
 if r.returncode or needle not in r.stdout:
  fail(name,(r.stdout+r.stderr).strip())
 print(f'PASS: {name}')
# Exit proof starts from a clean, synchronized repository.
r=cp(['git','status','--porcelain','--untracked-files=all'])
if r.returncode or r.stdout.strip(): fail('repository-clean',r.stdout.strip())
print('PASS: repository-clean')
r=cp(['git','rev-parse','HEAD']); o=cp(['git','rev-parse','origin/main'])
if r.returncode or o.returncode or r.stdout.strip()!=o.stdout.strip(): fail('repository-sync',f'HEAD={r.stdout.strip()} origin/main={o.stdout.strip()}')
print('PASS: repository-sync')
required=['governor/contracts/engineering-work.schema.json','governor/contracts/examples/stage10-smoke.json','scripts/validate-engineering-work-contract.py','tests/test_engineering_work_contract.py','scripts/run-stage10-gates.py','scripts/run-stage10-e2e-proof.py','homeassistant/verify-lifeos-dashboard.py']
missing=[p for p in required if not (REPO/p).is_file()]
if missing: fail('stage10-artifacts','missing:\n'+'\n'.join(missing))
print('PASS: stage10-artifacts')
run_gate('stage10-contract-gates','scripts/run-stage10-gates.py','STAGE10_GATES=PASS')
run_gate('stage10-e2e-proof','scripts/run-stage10-e2e-proof.py','STAGE10_E2E=PASS')
# Re-check cleanliness after all proofs: completion gate itself and children must be non-mutating.
r=cp(['git','status','--porcelain','--untracked-files=all'])
if r.returncode or r.stdout.strip(): fail('final-non-mutating',r.stdout.strip())
print('PASS: final-non-mutating')
print('STAGE10_EXIT=PASS')
print('contract=pass e2e=pass runtime=pass fail_closed=pass repository=clean synchronized=pass')
print('STAGE10=COMPLETE')
print('NEXT=Stage 11')
