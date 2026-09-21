#!/usr/bin/env python3
"""Stage 10 end-to-end contract lifecycle proof. Compact on PASS, diagnostic on FAIL."""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path
REPO=Path(__file__).resolve().parents[1]
FIXTURE=REPO/'governor/contracts/examples/stage10-smoke.json'
VALIDATOR=REPO/'scripts/validate-engineering-work-contract.py'
def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def diag(label,r): print(f'--- {label} ---\n{(r.stdout+r.stderr).strip() or "(no output)"}')
def fail(gate,detail=''):
 print(f'STAGE10_E2E=FAIL gate={gate}');
 if detail: print(detail)
 print('===== DIAGNOSTICS =====')
 for label,cmd in [('git',['git','status','--short','--branch']),('head',['git','log','-1','--oneline','--decorate']),('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}'])]: diag(label,cp(cmd))
 raise SystemExit(1)
def validate(data,expected=True):
 with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False) as f: json.dump(data,f); p=f.name
 try: r=cp([sys.executable,str(VALIDATOR),p])
 finally: Path(p).unlink(missing_ok=True)
 if expected and (r.returncode or 'CONTRACT_VALIDATION=PASS' not in r.stdout): fail('contract-lifecycle',(r.stdout+r.stderr).strip())
 if not expected and r.returncode==0: fail('fail-closed','invalid lifecycle state unexpectedly accepted')
 return r
try: base=json.loads(FIXTURE.read_text())
except Exception as e: fail('fixture',repr(e))
# Prove valid non-terminal lifecycle states.
for state in ['PLANNED','IMPLEMENTING','TESTING','READY_TO_DEPLOY','DEPLOYING','VERIFYING']:
 d=json.loads(json.dumps(base)); d['state']=state; validate(d)
print('PASS: lifecycle-nonterminal')
# Prove PASS is impossible before required evidence/results.
d=json.loads(json.dumps(base)); d['state']='PASS'; validate(d,False)
print('PASS: premature-pass-rejected')
# Build a complete terminal PASS contract with source/test/deploy/runtime evidence.
r=cp(['git','rev-parse','HEAD'])
if r.returncode: fail('source-commit',r.stderr.strip())
d=json.loads(json.dumps(base)); d['state']='PASS'; d['deployment']['source_commit']=r.stdout.strip(); d['tests'][0]['result']='PASS'; d['runtime_verification']['result']='PASS'; d['evidence']['records']=[{'kind':'commit','value':r.stdout.strip()},{'kind':'test','value':'engineering contract unit tests PASS'},{'kind':'deployment','value':'bounded gateway deployment proof'},{'kind':'runtime','value':'runtime health gate PASS'}]; validate(d)
print('PASS: terminal-pass-contract')
# Existing runtime verification is the real bounded runtime evidence gate.
r=cp([sys.executable,'homeassistant/verify-lifeos-dashboard.py'])
if r.returncode or 'LIFEOS_HA_GATE=PASS' not in r.stdout: fail('runtime-verification',(r.stdout+r.stderr).strip())
print('PASS: runtime-verification')
# Ensure repository remains clean: proof must not mutate runtime/source state.
r=cp(['git','status','--porcelain','--untracked-files=all'])
if r.returncode or r.stdout.strip(): fail('non-mutating-proof',r.stdout.strip())
print('PASS: non-mutating-proof')
print('STAGE10_E2E=PASS')
print('lifecycle=pass fail_closed=pass terminal_evidence=pass runtime=pass repository_clean=pass')
print('NEXT=Stage 10 completion/exit gate')
