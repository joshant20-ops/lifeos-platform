#!/usr/bin/env bash
set -Eeuo pipefail

EVIDENCE="/opt/lifeos-watch/octopus-powerdown-assurance/event-evidence-v52.jsonl"
STATUS="/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json"
EVENT_ID=5833

[ "$(id -u)" -eq 0 ] || { echo "FAIL: run with sudo/root" >&2; exit 1; }
[ -r "$EVIDENCE" ] || { echo "FAIL: evidence file missing" >&2; exit 1; }
[ -r "$STATUS" ] || { echo "FAIL: current status missing" >&2; exit 1; }

echo "===== POWER DOWN POST-EVENT ASSURANCE PROOF ====="
date -Is

python3 - "$EVIDENCE" "$STATUS" "$EVENT_ID" <<'PY'
import json,sys
from datetime import datetime

evfile,statusfile=sys.argv[1],sys.argv[2]
eid=int(sys.argv[3])
rows=[]
for line in open(evfile):
    try: rows.append(json.loads(line))
    except Exception: pass
status=json.load(open(statusfile))

pre=[]; active=[]; post=[]
for r in rows:
    e=r.get('event') or {}; n=e.get('next_event') or {}; rv=r.get('reserve') or {}; ctl=r.get('control') or {}; t=r.get('telemetry') or {}
    if not e.get('active') and n.get('id')==eid:
        pre.append(r)
    if e.get('active') and e.get('id')==eid:
        active.append(r)
    if not e.get('active') and ctl.get('action')=='POST_EVENT_RESERVE_RESTORE':
        post.append(r)

print('EVIDENCE_ROWS='+str(len(rows)))
print('PRE_EVENT_ROWS='+str(len(pre)))
print('ACTIVE_EVENT_ROWS='+str(len(active)))
print('RESTORE_ROWS='+str(len(post)))

checks=[]
checks.append((bool(pre),'pre-event evidence missing'))
checks.append((bool(active),'active-event evidence missing'))
checks.append((bool(post),'post-event restore evidence missing'))

if pre:
    p=pre[-1]; pr=p.get('readiness') or {}; rv=p.get('reserve') or {}; ctl=p.get('control') or {}; t=p.get('telemetry') or {}
    checks += [
      (pr.get('state')=='READY','pre-event battery readiness was not READY'),
      (rv.get('controller_owns_reserve') is False,'controller owned reserve before event'),
      (ctl.get('write_performed') is False,'pre-event write occurred'),
      (t.get('crosscheck_pass') is True,'pre-event crosscheck was not trusted'),
    ]
    print('PRE_EVENT_RESERVE_PERCENT='+str(rv.get('current_percent')))
    print('PRE_EVENT_USABLE_KWH='+str(pr.get('usable_energy_at_event_kwh')))

if active:
    good=[r for r in active if (r.get('control') or {}).get('action')=='ACTIVE_EVENT_RESERVE_RELEASE' and (r.get('control') or {}).get('blocked_reason') is None and (r.get('telemetry') or {}).get('crosscheck_pass') is True]
    checks.append((bool(good),'no unblocked trusted active-event reserve-release evidence'))
    owned=[r for r in active if (r.get('reserve') or {}).get('controller_owns_reserve') is True]
    checks.append((bool(owned),'controller never recorded reserve ownership during event'))
    min_seen=[r for r in active if (r.get('reserve') or {}).get('current_percent') is not None and (r.get('reserve') or {}).get('native_min_percent') is not None and abs(float((r.get('reserve') or {}).get('current_percent'))-float((r.get('reserve') or {}).get('native_min_percent')))<=0.5]
    checks.append((bool(min_seen),'reserve was never observed at native minimum during event'))
    print('ACTIVE_GOOD_ROWS='+str(len(good)))

if post:
    rr=post[-1]; rv=rr.get('reserve') or {}; ctl=rr.get('control') or {}
    checks += [
      (ctl.get('write_performed') is True,'restore action did not perform a write'),
      (rv.get('restored_this_run') is True,'restore run did not report restored_this_run'),
    ]

final_r=status.get('reserve') or {}; final_c=status.get('control') or {}
checks.append((final_r.get('controller_owns_reserve') is False,'controller still owns reserve after event'))
checks.append((final_c.get('blocked_reason') is None,'post-event controller remains blocked'))

if pre and final_r.get('current_percent') is not None:
    pre_pct=(pre[-1].get('reserve') or {}).get('current_percent')
    if pre_pct is not None:
        checks.append((abs(float(final_r.get('current_percent'))-float(pre_pct))<=0.5,'final reserve does not match pre-event reserve'))
        print('FINAL_RESERVE_PERCENT='+str(final_r.get('current_percent')))

failed=[m for ok,m in checks if not ok]
if failed:
    for m in failed: print('PROOF_FAIL='+m)
    raise SystemExit(1)
print('POWERDOWN_EVENT_ASSURANCE=PASS')
print('RESULT=PASS_POWERDOWN_COMPLIANCE_ASSURED')
PY
