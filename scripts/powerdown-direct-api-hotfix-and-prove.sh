#!/usr/bin/env bash
set -Eeuo pipefail

START_EPOCH="$(date +%s)"
REPO="/home/joshan/lifeos-platform"
SRC="homelab/live/usr/local/sbin/lifeos-powerdown-assurance-active"
LIVE_EXEC="/usr/local/sbin/lifeos-powerdown-assurance-active"
LIVE_OPT="/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
UNIT="lifeos-powerdown-assurance-active.service"
STATUS="/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json"
EVENT_ID=5833

e(){ local n d; n=$(date +%s); d=$((n-START_EPOCH)); printf '[%dm%02ds]' $((d/60)) $((d%60)); }
fail(){ echo "$(e) FAIL: $*" >&2; exit 1; }
pass(){ echo "$(e) PASS: $*"; }

[ "$(id -u)" -eq 0 ] || fail "run with sudo/root"
[ -d "$REPO/.git" ] || fail "repo missing"

TMP_BASE=$(mktemp)
TMP_NEW=$(mktemp)
trap 'rm -f "$TMP_BASE" "$TMP_NEW"' EXIT

echo "===== POWER DOWN DIRECT-API HOTFIX + PROOF ====="
echo "Expected: ~45-90 sec"
echo "Safety thresholds unchanged: max age 150s, timestamp delta 90s, diff 100W"
date -Is

git -C "$REPO" show origin/main:"$SRC" > "$TMP_BASE"

python3 - "$TMP_BASE" "$TMP_NEW" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text()

needle='HA = "http://127.0.0.1:8123"\n'
repl='HA = "http://127.0.0.1:8123"\nLIFEOS_ENERGY = "http://127.0.0.1:8110/api/energy/current"\n'
assert src.count(needle)==1, 'HA constant anchor mismatch'
src=src.replace(needle,repl,1)

needle='''def get(entity):\n    return api("/api/states/" + entity)\n\n\ndef numeric(entity):\n'''
repl='''def get(entity):\n    return api("/api/states/" + entity)\n\n\ndef lifeos_energy_current():\n    req = urllib.request.Request(LIFEOS_ENERGY)\n    with urllib.request.urlopen(req, timeout=10) as r:\n        return json.loads(r.read())\n\n\ndef numeric(entity):\n'''
assert src.count(needle)==1, 'function anchor mismatch'
src=src.replace(needle,repl,1)

needle='''baseline, baseline_obj = numeric(BASELINE)\ngrid_import, import_obj = numeric(IMPORT)\nenvoy_kw, envoy_obj = numeric(ENVOY)\n'''
repl='''baseline, baseline_obj = numeric(BASELINE)\n\n# Read authoritative LifeOS grid import directly from the live energy API.\n# This removes the HA REST polling hop which can stall after a timeout while\n# retaining the independent HA Envoy transport as a cross-check.\ntry:\n    energy_current = lifeos_energy_current()\n    grid_import = float(energy_current["grid_import_w"])\n    report_epoch = float(\n        energy_current.get("retrieved_at")\n        or energy_current.get("reading_time")\n    )\n    import_obj = {\n        "last_reported": datetime.fromtimestamp(\n            report_epoch, TZ\n        ).isoformat()\n    }\nexcept Exception:\n    grid_import = None\n    import_obj = {}\n\nenvoy_kw, envoy_obj = numeric(ENVOY)\n'''
assert src.count(needle)==1, 'telemetry anchor mismatch'
src=src.replace(needle,repl,1)

src=src.replace(
    '# Independent telemetry must agree repeatedly before an active-event\n',
    '# Redundant telemetry paths must agree repeatedly before an active-event\n',
    1,
)
Path(sys.argv[2]).write_text(src)
PY

python3 -m py_compile "$TMP_NEW" || fail "hotfixed controller syntax invalid"
grep -q 'LIFEOS_ENERGY = "http://127.0.0.1:8110/api/energy/current"' "$TMP_NEW" || fail "direct API patch missing"
grep -q 'MAX_SOURCE_AGE = 150' "$TMP_NEW" || fail "freshness threshold changed"
grep -q 'MAX_SOURCE_TIMESTAMP_DELTA = 90' "$TMP_NEW" || fail "timestamp threshold changed"
grep -q 'MAX_GRID_DIFF_W = 100' "$TMP_NEW" || fail "difference threshold changed"
pass "hotfix built; safety thresholds unchanged"

install -o root -g root -m 0755 "$TMP_NEW" "$LIVE_EXEC"
install -o root -g root -m 0755 "$TMP_NEW" "$LIVE_OPT"
pass "hotfixed controller installed to both runtime copies"

# Reset only accumulated cross-check confidence so the new telemetry path must
# earn trust from scratch. Preserve event/reserve state.
rm -f /opt/lifeos-watch/octopus-powerdown-assurance/grid-samples-v48.json

systemctl start "$UNIT" || fail "controller run 1 failed"
sleep 35
systemctl start "$UNIT" || fail "controller run 2 failed"
sleep 2

[ -r "$STATUS" ] || fail "status unreadable"
python3 - "$STATUS" "$EVENT_ID" <<'PY'
import json,sys
s=json.load(open(sys.argv[1])); eid=int(sys.argv[2])
e=s.get('event') or {}; n=e.get('next_event') or {}
r=s.get('readiness') or {}; t=s.get('telemetry') or {}; c=t.get('crosscheck') or {}
rv=s.get('reserve') or {}; ctl=s.get('control') or {}; flags=set(s.get('anomaly_flags') or [])
for k,v in [('STATUS_GENERATED_AT',s.get('generated_at')),('EVENT',e),('READINESS',r),('CROSSCHECK',c),('CROSSCHECK_PASS',t.get('crosscheck_pass')),('RESERVE',rv),('CONTROL',ctl),('ANOMALY_FLAGS',sorted(flags))]:
    print(k+'='+(json.dumps(v,sort_keys=True,separators=(',',':')) if isinstance(v,(dict,list)) else str(v)))
checks=[]
if e.get('active'):
    checks += [
      (e.get('id')==eid,'active event must be 5833'),
      (t.get('crosscheck_pass') is True,'crosscheck trust must PASS'),
      (c.get('current_good') is True,'current crosscheck must PASS'),
      (c.get('trusted') is True,'crosscheck must be trusted'),
      (ctl.get('blocked_reason') is None,'live event must not be blocked'),
    ]
else:
    checks += [
      (n.get('id')==eid,'joined event 5833 must be next'),
      (r.get('state')=='READY','battery readiness must be READY'),
      (t.get('crosscheck_pass') is True,'crosscheck trust must PASS'),
      (c.get('current_good') is True,'current crosscheck must PASS'),
      (c.get('trusted') is True,'crosscheck must be trusted'),
      (int(c.get('good_runs') or 0)>=2,'two consecutive good runs required'),
      (rv.get('controller_owns_reserve') is False,'reserve must remain untouched pre-event'),
      (ctl.get('write_performed') is False,'no pre-event battery write permitted'),
    ]
checks += [
  ('authoritative_grid_stale' not in flags,'authoritative grid source must be fresh'),
  ('aligned_crosscheck_unavailable' not in flags,'crosscheck must be available'),
]
failed=[m for ok,m in checks if not ok]
if failed:
    [print('PROOF_FAIL='+m) for m in failed]
    raise SystemExit(1)
print('POWERDOWN_DIRECT_API_PROOF=PASS')
PY

pass "direct API telemetry fresh and safety trust rebuilt"
echo "RESULT=PASS_POWERDOWN_READY"
