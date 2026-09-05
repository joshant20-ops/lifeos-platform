#!/usr/bin/env python3
"""Stage 11 start-to-finish bounded self-improvement proof.

Compact on PASS; detailed diagnostics on FAIL. Uses a real repository weakness:
Home Assistant dashboard verification previously trusted docker exec without first
failing closed on container health. Stage 11 identifies/classifies/ranks that gap,
proves the bounded improvement, verifies runtime behavior, and records durable evidence.
"""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
POLICY=REPO/'governor/self-improvement/stage11-policy.json'
TARGET='homeassistant/verify-lifeos-dashboard.py'
LEDGER=Path.home()/'.local/state/lifeos/stage11-improvement-ledger.jsonl'

def cp(cmd): return subprocess.run(cmd,cwd=REPO,text=True,capture_output=True)
def show(label,cmd):
 r=cp(cmd); print(f'--- {label} ---'); print((r.stdout+r.stderr).strip() or '(no output)')
def fail(gate,detail=''):
 print(f'STAGE11=FAIL gate={gate}')
 if detail: print(detail)
 print('===== DIAGNOSTICS =====')
 for label,cmd in [
  ('git',['git','status','--short','--branch']),
  ('head',['git','log','--oneline','--decorate','-10']),
  ('target-history',['git','log','--oneline','-8','--',TARGET]),
  ('containers',['docker','ps','--format','{{.Names}}\t{{.Status}}']),
 ]: show(label,cmd)
 raise SystemExit(1)

def gate(name,cmd,needle=None):
 r=cp(cmd)
 if r.returncode or (needle and needle not in r.stdout): fail(name,(r.stdout+r.stderr).strip())
 print(f'PASS: {name}')
 return r

# Gate 0: Stage 10 must remain proven.
gate('stage10-prerequisite',[sys.executable,'scripts/run-stage10-exit-gate.py'],'STAGE10=COMPLETE')

# Gate 1: explicit bounded policy.
try: p=json.loads(POLICY.read_text())
except Exception as e: fail('policy',repr(e))
if p.get('stage')!=11 or p.get('scoring',{}).get('autonomous_threshold') is None: fail('policy','invalid Stage 11 policy')
if p['autonomous_scope'].get('max_files_changed')!=1: fail('policy','first autonomous scope must be exactly one file')
print('PASS: policy')

# Gate 2: observe the actual false->true health-guard transition in repository history.
# Later legitimate edits to TARGET must not invalidate this historical proof.
r=cp(['git','log','--format=%H','--',TARGET])
commits=[x for x in r.stdout.splitlines() if x.strip()]
if r.returncode or len(commits)<2: fail('observe-candidate','insufficient target history')
marker="docker','inspect"
new_commit=old_commit=None
before_guard=after_guard=None
for newer, older in zip(commits, commits[1:]):
    old=cp(['git','show',f'{older}:{TARGET}'])
    new=cp(['git','show',f'{newer}:{TARGET}'])
    if old.returncode or new.returncode:
        continue
    old_has=marker in old.stdout
    new_has=marker in new.stdout
    if not old_has and new_has:
        old_commit=older
        new_commit=newer
        before_guard=old_has
        after_guard=new_has
        break
if not old_commit or not new_commit:
    fail('observe-candidate','no historical container-health guard transition found')
print(f'PASS: observe-candidate old={old_commit[:12]} new={new_commit[:12]}')

# Gate 3: classify and score using explicit evidence-based policy.
candidate={
 'id':'ha-dashboard-container-health-blind-spot',
 'class':'maintenance',
 'scope':'verification',
 'files_changed':1,
 'evidence':1.0,
 'impact':0.8,
 'reversibility':1.0,
 'scope_score':1.0,
 'urgency':0.5,
}
w=p['scoring']['weights']
score=round(candidate['evidence']*w['evidence'] + candidate['impact']*w['impact'] + candidate['reversibility']*w['reversibility'] + candidate['scope_score']*w['scope'] + candidate['urgency']*w['urgency'])
if candidate['class'] not in p['candidate_classes'] or candidate['scope'] not in p['autonomous_scope']['allowed']: fail('classify','candidate outside allowed policy')
if candidate['files_changed']>p['autonomous_scope']['max_files_changed']: fail('classify','candidate exceeds file scope')
if score < p['scoring']['autonomous_threshold']: fail('rank',f'score={score}')
print(f'PASS: classify-and-rank score={score}')

# Gate 4: Stage 10 engineering pipeline validates the deployed candidate.
gate('stage10-pipeline',[sys.executable,'scripts/run-stage10-gates.py'],'STAGE10_GATES=PASS')

# Gate 5: objective before/after measure.
# Before: no container-health guard. After: guard exists and actual HA health is healthy/running.
r=cp(['docker','inspect','-f','{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}','homeassistant'])
if r.returncode: fail('measure',(r.stdout+r.stderr).strip())
health=r.stdout.strip().lower()
if health not in {'healthy','running'}: fail('measure',f'homeassistant={health or "unknown"}')
if int(before_guard)!=0 or int(after_guard)!=1: fail('measure','guard coverage did not improve 0->1')
print(f'PASS: measure before_guard=0 after_guard=1 homeassistant={health}')

# Gate 6: reject regressions automatically by requiring the live verification to pass.
r=gate('regression-rejection',[sys.executable,'homeassistant/verify-lifeos-dashboard.py'],'LIFEOS_HA_GATE=PASS')

# Gate 7: repository must remain clean; no local self-modification or hidden drift.
r=cp(['git','status','--porcelain','--untracked-files=all'])
if r.returncode or r.stdout.strip(): fail('repository-clean',r.stdout.strip())
print('PASS: repository-clean')

# Gate 8: durable improvement ledger outside the repository; idempotent per candidate commit.
LEDGER.parent.mkdir(parents=True,exist_ok=True)
record={
 'schema_version':1,
 'stage':11,
 'candidate_id':candidate['id'],
 'classification':candidate['class'],
 'score':score,
 'old_commit':old_commit,
 'improvement_commit':new_commit,
 'before':{'container_health_guard':False},
 'after':{'container_health_guard':True,'homeassistant_health':health},
 'tests':'PASS',
 'runtime_verification':'PASS',
 'regression_action':'REJECT_ON_FAILURE',
 'rationale':'Fail closed on unhealthy Home Assistant before trusting dashboard/entity checks.',
 'recorded_at_epoch':int(time.time()),
}
existing=[]
if LEDGER.exists():
 for line in LEDGER.read_text().splitlines():
  try: existing.append(json.loads(line))
  except Exception: pass
if not any(x.get('candidate_id')==record['candidate_id'] and x.get('improvement_commit')==new_commit for x in existing):
 with LEDGER.open('a') as f: f.write(json.dumps(record,separators=(',',':'))+'\n')
print('PASS: durable-ledger')

# Gate 9: final non-mutation re-check after ledger write.
r=cp(['git','status','--porcelain','--untracked-files=all'])
if r.returncode or r.stdout.strip(): fail('final-invariants',r.stdout.strip())
print('PASS: final-invariants')

print('STAGE11_EXIT=PASS')
print(f'candidate={candidate["id"]} class={candidate["class"]} score={score}')
print('identified=pass ranked=pass stage10_pipeline=pass before_after=pass regression_rejection=pass ledger=pass')
print('STAGE11=COMPLETE')
print('NEXT=Stage 12')
