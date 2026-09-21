#!/usr/bin/env bash
set -Eeuo pipefail

START_EPOCH="$(date +%s)"
REPO="/home/joshan/lifeos-platform"
WT="$(mktemp -d /tmp/lifeos-powerdown-v52.XXXXXX)"
SRC_EXEC="homelab/live/usr/local/sbin/lifeos-powerdown-assurance-active"
SRC_OPT="homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
REC="homelab/live/usr/local/sbin/lifeos-powerdown-evidence-recorder"
REC_SERVICE="homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-evidence-recorder.service"
REC_TIMER="homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-evidence-recorder.timer"
LIVE_EXEC="/usr/local/sbin/lifeos-powerdown-assurance-active"
LIVE_OPT="/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
UNIT="lifeos-powerdown-assurance-active.service"
STATUS="/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json"
EVENT_ID=5833

elapsed(){ local n d; n=$(date +%s); d=$((n-START_EPOCH)); printf '[%dm%02ds]' $((d/60)) $((d%60)); }
fail(){ echo "$(elapsed) FAIL: $*" >&2; exit 1; }
pass(){ echo "$(elapsed) PASS: $*"; }
cleanup(){ git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; }
trap cleanup EXIT

[ "$(id -u)" -ne 0 ] || fail "run as joshan, not root"
[ -d "$REPO/.git" ] || fail "repo missing"
sudo -v || fail "sudo authorization failed"

echo "===== LIFEOS POWER DOWN V52 PERMANENTIZE ====="
echo "Expected: ~1-2 min"
echo "Purpose: make proven direct-API telemetry canonical and enable read-only event evidence capture"
date -Is

git -C "$REPO" fetch origin main >/dev/null
git -C "$REPO" worktree add --detach "$WT" origin/main >/dev/null

python3 - "$WT/$SRC_EXEC" "$WT/$SRC_OPT" <<'PY'
from pathlib import Path
import sys
p1,p2=map(Path,sys.argv[1:])
src=p1.read_text()
if 'LIFEOS_ENERGY = "http://127.0.0.1:8110/api/energy/current"' not in src:
    a='HA = "http://127.0.0.1:8123"\n'
    b='HA = "http://127.0.0.1:8123"\nLIFEOS_ENERGY = "http://127.0.0.1:8110/api/energy/current"\n'
    assert src.count(a)==1, 'HA constant anchor mismatch'
    src=src.replace(a,b,1)
    a='''def get(entity):\n    return api("/api/states/" + entity)\n\n\ndef numeric(entity):\n'''
    b='''def get(entity):\n    return api("/api/states/" + entity)\n\n\ndef lifeos_energy_current():\n    req = urllib.request.Request(LIFEOS_ENERGY)\n    with urllib.request.urlopen(req, timeout=10) as r:\n        return json.loads(r.read())\n\n\ndef numeric(entity):\n'''
    assert src.count(a)==1, 'function anchor mismatch'
    src=src.replace(a,b,1)
    a='''baseline, baseline_obj = numeric(BASELINE)\ngrid_import, import_obj = numeric(IMPORT)\nenvoy_kw, envoy_obj = numeric(ENVOY)\n'''
    b='''baseline, baseline_obj = numeric(BASELINE)\n\n# Authoritative grid import is read directly from the live LifeOS Energy API.\n# This avoids the Home Assistant REST polling hop, which can stall after a\n# timeout, while retaining the HA Envoy transport as a redundant cross-check.\ntry:\n    energy_current = lifeos_energy_current()\n    grid_import = float(energy_current["grid_import_w"])\n    report_epoch = float(\n        energy_current.get("retrieved_at")\n        or energy_current.get("reading_time")\n    )\n    import_obj = {\n        "last_reported": datetime.fromtimestamp(\n            report_epoch, TZ\n        ).isoformat()\n    }\nexcept Exception:\n    grid_import = None\n    import_obj = {}\n\nenvoy_kw, envoy_obj = numeric(ENVOY)\n'''
    assert src.count(a)==1, 'telemetry anchor mismatch'
    src=src.replace(a,b,1)
    src=src.replace('# Independent telemetry must agree repeatedly before an active-event\n','# Redundant telemetry paths must agree repeatedly before an active-event\n',1)
p1.write_text(src)
p2.write_text(src)
PY

python3 -m py_compile "$WT/$SRC_EXEC" || fail "canonical controller syntax invalid"
cmp -s "$WT/$SRC_EXEC" "$WT/$SRC_OPT" || fail "canonical controller copies diverge"
grep -q 'LIFEOS_ENERGY = "http://127.0.0.1:8110/api/energy/current"' "$WT/$SRC_EXEC" || fail "direct API path missing"
grep -q 'MAX_SOURCE_AGE = 150' "$WT/$SRC_EXEC" || fail "freshness gate changed"
grep -q 'MAX_SOURCE_TIMESTAMP_DELTA = 90' "$WT/$SRC_EXEC" || fail "timestamp gate changed"
grep -q 'MAX_GRID_DIFF_W = 100' "$WT/$SRC_EXEC" || fail "difference gate changed"
pass "canonical V52 controller validated"

git -C "$WT" add "$SRC_EXEC" "$SRC_OPT"
if ! git -C "$WT" diff --cached --quiet; then
  git -C "$WT" -c user.name='LifeOS Incident Recovery' -c user.email='lifeos@localhost' commit -m 'powerdown: make direct API telemetry canonical' >/dev/null
  git -C "$WT" push origin HEAD:main >/dev/null
  pass "canonical V52 committed and pushed"
else
  pass "canonical V52 already present on main"
fi

CANON_SHA="$(sha256sum "$WT/$SRC_EXEC" | awk '{print $1}')"
sudo install -o root -g root -m 0755 "$WT/$SRC_EXEC" "$LIVE_EXEC"
sudo install -o root -g root -m 0755 "$WT/$SRC_OPT" "$LIVE_OPT"
[ "$(sha256sum "$LIVE_EXEC" | awk '{print $1}')" = "$CANON_SHA" ] || fail "live executable differs from canonical"
[ "$(sha256sum "$LIVE_OPT" | awk '{print $1}')" = "$CANON_SHA" ] || fail "live /opt copy differs from canonical"
pass "live controller exactly matches canonical V52"

sudo install -o root -g root -m 0755 "$WT/$REC" /usr/local/sbin/lifeos-powerdown-evidence-recorder
sudo install -o root -g root -m 0644 "$WT/$REC_SERVICE" /etc/systemd/system/lifeos-powerdown-evidence-recorder.service
sudo install -o root -g root -m 0644 "$WT/$REC_TIMER" /etc/systemd/system/lifeos-powerdown-evidence-recorder.timer
sudo systemctl daemon-reload
sudo systemctl enable --now lifeos-powerdown-evidence-recorder.timer >/dev/null
sudo systemctl start "$UNIT"
sleep 3
sudo systemctl start lifeos-powerdown-evidence-recorder.service
pass "30-second read-only event evidence capture enabled"

sudo python3 - "$STATUS" "$EVENT_ID" <<'PY'
import json,sys
s=json.load(open(sys.argv[1])); eid=int(sys.argv[2])
e=s.get('event') or {}; n=e.get('next_event') or {}; r=s.get('readiness') or {}
t=s.get('telemetry') or {}; c=t.get('crosscheck') or {}; rv=s.get('reserve') or {}; ctl=s.get('control') or {}; flags=set(s.get('anomaly_flags') or [])
print('STATUS_GENERATED_AT='+str(s.get('generated_at')))
print('EVENT='+json.dumps(e,sort_keys=True,separators=(',',':')))
print('READINESS='+json.dumps(r,sort_keys=True,separators=(',',':')))
print('CROSSCHECK='+json.dumps(c,sort_keys=True,separators=(',',':')))
print('RESERVE='+json.dumps(rv,sort_keys=True,separators=(',',':')))
print('CONTROL='+json.dumps(ctl,sort_keys=True,separators=(',',':')))
print('ANOMALY_FLAGS='+json.dumps(sorted(flags),separators=(',',':')))
checks=[
 (t.get('crosscheck_pass') is True,'crosscheck trust must PASS'),
 (c.get('current_good') is True,'current crosscheck must PASS'),
 (c.get('trusted') is True,'crosscheck must be trusted'),
 ('authoritative_grid_stale' not in flags,'authoritative source must be fresh'),
 ('aligned_crosscheck_unavailable' not in flags,'crosscheck must be available'),
]
if e.get('active'):
 checks += [(e.get('id')==eid,'active event must be 5833'),(ctl.get('blocked_reason') is None,'active control must not be blocked')]
else:
 checks += [(n.get('id')==eid,'joined event 5833 must be next'),(r.get('state')=='READY','battery must be READY'),(rv.get('controller_owns_reserve') is False,'reserve must be untouched pre-event')]
failed=[m for ok,m in checks if not ok]
if failed:
 [print('PROOF_FAIL='+m) for m in failed]
 raise SystemExit(1)
print('V52_CANONICAL_LIVE_PROOF=PASS')
PY

HEAD="$(git -C "$WT" rev-parse HEAD)"
echo "CANONICAL_COMMIT=$HEAD"
echo "CANONICAL_SHA256=$CANON_SHA"
echo "RESULT=PASS_POWERDOWN_V52_PERMANENT"
