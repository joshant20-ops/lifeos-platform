#!/usr/bin/env bash
set -Eeuo pipefail

# Bounded emergency launcher for the 2026-09-01 Power Down incident.
# Installs only the canonical Power Down controller into its two managed live
# locations, runs the existing oneshot twice to rebuild cross-check trust, and
# fails unless the pre-event live status is genuinely green.

START_EPOCH="$(date +%s)"
REPO="/home/joshan/lifeos-platform"
GIT_USER="joshan"
EXPECTED_CONTROLLER_BLOB="c3dc4db17156dfdd1fdf5128c7100de447056ffd"
SRC_EXEC="homelab/live/usr/local/sbin/lifeos-powerdown-assurance-active"
SRC_OPT="homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
LIVE_EXEC="/usr/local/sbin/lifeos-powerdown-assurance-active"
LIVE_OPT="/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
STATUS="/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json"
UNIT="lifeos-powerdown-assurance-active.service"
EVENT_ID=5833

elapsed() {
  local now d
  now="$(date +%s)"; d=$((now-START_EPOCH))
  printf '[%dm%02ds]' $((d/60)) $((d%60))
}

fail() { echo "$(elapsed) FAIL: $*" >&2; exit 1; }
pass() { echo "$(elapsed) PASS: $*"; }

[ "$(id -u)" -eq 0 ] || fail "run with sudo/root"
[ -d "$REPO/.git" ] || fail "canonical repo missing: $REPO"

TMP_EXEC="$(mktemp)"
TMP_OPT="$(mktemp)"
BACKUP_EXEC="$(mktemp)"
BACKUP_OPT="$(mktemp)"
cleanup() { rm -f "$TMP_EXEC" "$TMP_OPT" "$BACKUP_EXEC" "$BACKUP_OPT"; }
trap cleanup EXIT

echo "===== LIFEOS POWER DOWN INCIDENT DEPLOY + PROVE ====="
echo "Expected: about 15-45 sec"
echo "Writes: two protected controller files only; service executions use existing event-only gates"

sudo -u "$GIT_USER" git -C "$REPO" fetch origin main >/dev/null
REMOTE_HEAD="$(sudo -u "$GIT_USER" git -C "$REPO" rev-parse origin/main)"
echo "ORIGIN_MAIN=$REMOTE_HEAD"

sudo -u "$GIT_USER" git -C "$REPO" show "origin/main:$SRC_EXEC" >"$TMP_EXEC"
sudo -u "$GIT_USER" git -C "$REPO" show "origin/main:$SRC_OPT" >"$TMP_OPT"

BLOB_EXEC="$(git hash-object "$TMP_EXEC")"
BLOB_OPT="$(git hash-object "$TMP_OPT")"
SHA_EXEC="$(sha256sum "$TMP_EXEC" | awk '{print $1}')"
SHA_OPT="$(sha256sum "$TMP_OPT" | awk '{print $1}')"
echo "CANONICAL_EXEC_BLOB=$BLOB_EXEC"
echo "CANONICAL_OPT_BLOB=$BLOB_OPT"
echo "CANONICAL_EXEC_SHA256=$SHA_EXEC"
echo "CANONICAL_OPT_SHA256=$SHA_OPT"
[ "$BLOB_EXEC" = "$BLOB_OPT" ] || fail "canonical Power Down copies diverge"
[ "$BLOB_EXEC" = "$EXPECTED_CONTROLLER_BLOB" ] || fail "canonical controller is not the reviewed incident blob"
python3 -m py_compile "$TMP_EXEC" || fail "canonical controller syntax failed"
pass "canonical controller exact Git blob + syntax verified"

[ -f "$LIVE_EXEC" ] || fail "live executable missing"
[ -f "$LIVE_OPT" ] || fail "live /opt controller missing"
cp -a "$LIVE_EXEC" "$BACKUP_EXEC"
cp -a "$LIVE_OPT" "$BACKUP_OPT"

install -o root -g root -m 0755 "$TMP_EXEC" "$LIVE_EXEC"
install -o root -g root -m 0755 "$TMP_OPT" "$LIVE_OPT"

LIVE_EXEC_BLOB="$(git hash-object "$LIVE_EXEC")"
LIVE_OPT_BLOB="$(git hash-object "$LIVE_OPT")"
[ "$LIVE_EXEC_BLOB" = "$EXPECTED_CONTROLLER_BLOB" ] || fail "live executable blob mismatch after install"
[ "$LIVE_OPT_BLOB" = "$EXPECTED_CONTROLLER_BLOB" ] || fail "live /opt blob mismatch after install"
pass "protected runtime copies installed exactly from canonical GitHub bytes"

systemctl start "$UNIT" || {
  install -o root -g root -m 0755 "$BACKUP_EXEC" "$LIVE_EXEC"
  install -o root -g root -m 0755 "$BACKUP_OPT" "$LIVE_OPT"
  fail "first controller run failed; previous runtime restored"
}
sleep 5
systemctl start "$UNIT" || fail "second controller run failed"
sleep 2

[ -r "$STATUS" ] || fail "status file unreadable after controller runs"

python3 - "$STATUS" "$EVENT_ID" <<'PY'
import json, sys

path=sys.argv[1]
event_id=int(sys.argv[2])
s=json.load(open(path))
print("STATUS_GENERATED_AT="+str(s.get("generated_at")))
print("EVENT="+json.dumps(s.get("event"),sort_keys=True,separators=(",",":")))
print("READINESS="+json.dumps(s.get("readiness"),sort_keys=True,separators=(",",":")))
print("CROSSCHECK="+json.dumps((s.get("telemetry") or {}).get("crosscheck"),sort_keys=True,separators=(",",":")))
print("CROSSCHECK_PASS="+str((s.get("telemetry") or {}).get("crosscheck_pass")))
print("RESERVE="+json.dumps(s.get("reserve"),sort_keys=True,separators=(",",":")))
print("CONTROL="+json.dumps(s.get("control"),sort_keys=True,separators=(",",":")))
print("ANOMALY_FLAGS="+json.dumps(s.get("anomaly_flags"),separators=(",",":")))

event=s.get("event") or {}
next_event=event.get("next_event") or {}
readiness=s.get("readiness") or {}
telemetry=s.get("telemetry") or {}
cross=telemetry.get("crosscheck") or {}
reserve=s.get("reserve") or {}
control=s.get("control") or {}
flags=set(s.get("anomaly_flags") or [])

checks=[]
checks.append((not event.get("active"),"event must still be pre-event for this readiness proof"))
checks.append((next_event.get("id")==event_id,"joined event ID 5833 must be the next event"))
checks.append((readiness.get("state")=="READY","battery readiness must be READY"))
checks.append((telemetry.get("crosscheck_pass") is True,"crosscheck trust must PASS"))
checks.append((cross.get("current_good") is True,"current crosscheck must PASS"))
checks.append((cross.get("trusted") is True,"crosscheck must be trusted"))
checks.append((int(cross.get("good_runs") or 0)>=2,"at least two consecutive good crosscheck runs required"))
checks.append(("authoritative_grid_stale" not in flags,"authoritative grid source must not be stale"))
checks.append(("aligned_crosscheck_unavailable" not in flags,"independent crosscheck must be available"))
checks.append((reserve.get("controller_owns_reserve") is False,"LifeOS must not own reserve before event"))
checks.append((control.get("write_performed") is False,"no pre-event battery write permitted"))
checks.append((control.get("action")=="NO_WRITE_OUTSIDE_EVENT","pre-event action must remain no-write"))

failed=[msg for ok,msg in checks if not ok]
if failed:
    for msg in failed:
        print("PROOF_FAIL="+msg)
    raise SystemExit(1)
print("POWERDOWN_PRE_EVENT_PROOF=PASS")
PY

pass "Power Down event joined, battery READY, cross-check trusted, reserve untouched"
echo "RESULT=PASS_READY_FOR_18_00_EVENT"
