#!/usr/bin/env bash
set -Eeuo pipefail

START_EPOCH="$(date +%s)"
UNIT="lifeos-powerdown-assurance-active.service"
STATUS="/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json"
EVENT_ID=5833

echo "===== POWER DOWN FINAL PRE-EVENT PROOF ====="
echo "Expected: ~45 sec"
date -Is

systemctl start "$UNIT"
sleep 35
systemctl start "$UNIT"
sleep 2

python3 - "$STATUS" "$EVENT_ID" <<'PY'
import json, sys
s=json.load(open(sys.argv[1])); eid=int(sys.argv[2])
e=s.get('event') or {}; n=e.get('next_event') or {}
r=s.get('readiness') or {}; t=s.get('telemetry') or {}; c=t.get('crosscheck') or {}
rv=s.get('reserve') or {}; ctl=s.get('control') or {}; flags=set(s.get('anomaly_flags') or [])
print('STATUS_GENERATED_AT='+str(s.get('generated_at')))
print('EVENT='+json.dumps(e,sort_keys=True,separators=(',',':')))
print('READINESS='+json.dumps(r,sort_keys=True,separators=(',',':')))
print('CROSSCHECK='+json.dumps(c,sort_keys=True,separators=(',',':')))
print('CROSSCHECK_PASS='+str(t.get('crosscheck_pass')))
print('RESERVE='+json.dumps(rv,sort_keys=True,separators=(',',':')))
print('CONTROL='+json.dumps(ctl,sort_keys=True,separators=(',',':')))
print('ANOMALY_FLAGS='+json.dumps(sorted(flags),separators=(',',':')))
checks=[
 (not e.get('active'),'event must still be pre-event'),
 (n.get('id')==eid,'joined event ID 5833 must be next'),
 (r.get('state')=='READY','battery readiness must be READY'),
 (t.get('crosscheck_pass') is True,'crosscheck trust must PASS'),
 (c.get('current_good') is True,'current crosscheck must PASS'),
 (c.get('trusted') is True,'crosscheck must be trusted'),
 (int(c.get('good_runs') or 0)>=2,'at least two consecutive good runs required'),
 ('authoritative_grid_stale' not in flags,'authoritative grid source must be fresh'),
 ('aligned_crosscheck_unavailable' not in flags,'independent crosscheck must be available'),
 (rv.get('controller_owns_reserve') is False,'LifeOS must not own reserve before event'),
 (ctl.get('write_performed') is False,'no pre-event battery write permitted'),
]
failed=[m for ok,m in checks if not ok]
if failed:
  for m in failed: print('PROOF_FAIL='+m)
  raise SystemExit(1)
print('POWERDOWN_FINAL_PRE_EVENT_PROOF=PASS')
print('RESULT=PASS_POWERDOWN_READY')
PY
