#!/usr/bin/env bash
set -Eeuo pipefail

START_EPOCH="$(date +%s)"
HA_CONTAINER="homeassistant"
UNIT="lifeos-powerdown-assurance-active.service"
STATUS="/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json"
SECRET="/usr/local/sbin/lifeos-secret"
EVENT_ID=5833
MAX_SENSOR_AGE=150

elapsed() {
  local now d
  now="$(date +%s)"; d=$((now-START_EPOCH))
  printf '[%dm%02ds]' $((d/60)) $((d%60))
}
fail() { echo "$(elapsed) FAIL: $*" >&2; exit 1; }
pass() { echo "$(elapsed) PASS: $*"; }

[ "$(id -u)" -eq 0 ] || fail "run with sudo/root"
[ -x "$SECRET" ] || fail "lifeos-secret helper missing"

ha_post() {
  local endpoint="$1"
  "$SECRET" exec homeassistant.long_lived_access_token HA_TOKEN \
    python3 - "$endpoint" <<'PY'
import os, sys, urllib.request
endpoint=sys.argv[1]
req=urllib.request.Request(
    "http://127.0.0.1:8123"+endpoint,
    method="POST",
    data=b"{}",
    headers={"Authorization":"Bearer "+os.environ["HA_TOKEN"],"Content-Type":"application/json"},
)
with urllib.request.urlopen(req, timeout=20) as r:
    print("HA_POST_STATUS="+str(r.status))
PY
}

sensor_snapshot() {
  "$SECRET" exec homeassistant.long_lived_access_token HA_TOKEN python3 - <<'PY'
import json, os, time, urllib.request
from datetime import datetime
entities=["sensor.lifeos_energy_grid_import","sensor.lifeos_grid_import_power","sensor.envoy_122425011227_current_net_power_consumption"]
for e in entities:
    req=urllib.request.Request("http://127.0.0.1:8123/api/states/"+e,headers={"Authorization":"Bearer "+os.environ["HA_TOKEN"]})
    with urllib.request.urlopen(req,timeout=15) as r: o=json.load(r)
    stamp=o.get("last_reported") or o.get("last_updated")
    age=999999.0
    if stamp:
        age=time.time()-datetime.fromisoformat(stamp.replace("Z","+00:00")).timestamp()
    print(f"ENTITY={e} STATE={o.get('state')} AGE_SECONDS={age:.1f} LAST_REPORTED={o.get('last_reported')} LAST_UPDATED={o.get('last_updated')}")
PY
}

lifeos_sensor_fresh() {
  "$SECRET" exec homeassistant.long_lived_access_token HA_TOKEN python3 - "$MAX_SENSOR_AGE" <<'PY'
import json, os, sys, time, urllib.request
from datetime import datetime
limit=float(sys.argv[1])
for e in ("sensor.lifeos_energy_grid_import","sensor.lifeos_grid_import_power"):
    req=urllib.request.Request("http://127.0.0.1:8123/api/states/"+e,headers={"Authorization":"Bearer "+os.environ["HA_TOKEN"]})
    with urllib.request.urlopen(req,timeout=15) as r: o=json.load(r)
    stamp=o.get("last_reported") or o.get("last_updated")
    if not stamp: raise SystemExit(1)
    age=time.time()-datetime.fromisoformat(stamp.replace("Z","+00:00")).timestamp()
    if age > limit: raise SystemExit(1)
PY
}

wait_ha_healthy() {
  local i status health
  for i in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Status}}' "$HA_CONTAINER" 2>/dev/null || true)"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$HA_CONTAINER" 2>/dev/null || true)"
    if [ "$status" = running ] && { [ "$health" = healthy ] || [ "$health" = none ]; }; then
      return 0
    fi
    sleep 3
  done
  return 1
}

echo "===== POWER DOWN HA REST RECOVERY + PROOF ====="
echo "Expected: about 2-5 min"
echo "Safety: does not weaken any Power Down gate; HA restart only if reload fails"
date -Is

echo
echo "===== 1/5 — CURRENT SENSOR STATE ====="
sensor_snapshot || true

echo
echo "===== 2/5 — NON-DISRUPTIVE HA RELOAD ====="
if ha_post /api/services/homeassistant/reload_all; then
  pass "Home Assistant reload requested"
else
  echo "$(elapsed) WARN: reload_all unavailable/failed"
fi

echo "Waiting 75s for the 60s REST poll to execute..."
sleep 75

if lifeos_sensor_fresh; then
  pass "LifeOS REST + template sensors recovered after reload"
else
  echo "$(elapsed) WARN: sensors still stale; restarting Home Assistant container"
  docker restart "$HA_CONTAINER" >/dev/null || fail "Home Assistant container restart failed"
  wait_ha_healthy || fail "Home Assistant did not become healthy after restart"
  pass "Home Assistant restarted and healthy"
  echo "Waiting 75s for REST poll after restart..."
  sleep 75
  lifeos_sensor_fresh || {
    sensor_snapshot || true
    fail "LifeOS REST sensors remain stale after HA restart"
  }
  pass "LifeOS REST + template sensors fresh after restart"
fi

echo
echo "===== 3/5 — FRESHNESS EVIDENCE ====="
sensor_snapshot

echo
echo "===== 4/5 — REBUILD POWER DOWN CROSS-CHECK TRUST ====="
systemctl start "$UNIT" || fail "first Power Down controller run failed"
sleep 35
systemctl start "$UNIT" || fail "second Power Down controller run failed"
sleep 2

[ -r "$STATUS" ] || fail "Power Down status unreadable"

echo
echo "===== 5/5 — LIVE POWER DOWN PROOF ====="
python3 - "$STATUS" "$EVENT_ID" <<'PY'
import json, sys
s=json.load(open(sys.argv[1])); eid=int(sys.argv[2])
event=s.get("event") or {}; nxt=event.get("next_event") or {}
readiness=s.get("readiness") or {}; tele=s.get("telemetry") or {}; cross=tele.get("crosscheck") or {}
reserve=s.get("reserve") or {}; control=s.get("control") or {}; flags=set(s.get("anomaly_flags") or [])
print("STATUS_GENERATED_AT="+str(s.get("generated_at")))
print("EVENT="+json.dumps(event,sort_keys=True,separators=(",",":")))
print("READINESS="+json.dumps(readiness,sort_keys=True,separators=(",",":")))
print("CROSSCHECK="+json.dumps(cross,sort_keys=True,separators=(",",":")))
print("CROSSCHECK_PASS="+str(tele.get("crosscheck_pass")))
print("RESERVE="+json.dumps(reserve,sort_keys=True,separators=(",",":")))
print("CONTROL="+json.dumps(control,sort_keys=True,separators=(",",":")))
print("ANOMALY_FLAGS="+json.dumps(sorted(flags),separators=(",",":")))
checks=[]
if event.get("active"):
    checks += [
      (event.get("id")==eid,"active event must be ID 5833"),
      (tele.get("crosscheck_pass") is True,"crosscheck trust must PASS"),
      (cross.get("current_good") is True,"current crosscheck must PASS"),
      (cross.get("trusted") is True,"crosscheck must be trusted"),
      ("authoritative_grid_stale" not in flags,"authoritative grid source must not be stale"),
      ("aligned_crosscheck_unavailable" not in flags,"independent crosscheck must be available"),
      (control.get("blocked_reason") is None,"live event control must not be blocked"),
    ]
else:
    checks += [
      (nxt.get("id")==eid,"joined event ID 5833 must be next"),
      (readiness.get("state")=="READY","battery readiness must be READY"),
      (tele.get("crosscheck_pass") is True,"crosscheck trust must PASS"),
      (cross.get("current_good") is True,"current crosscheck must PASS"),
      (cross.get("trusted") is True,"crosscheck must be trusted"),
      (int(cross.get("good_runs") or 0)>=2,"at least two consecutive good runs required"),
      ("authoritative_grid_stale" not in flags,"authoritative grid source must not be stale"),
      ("aligned_crosscheck_unavailable" not in flags,"independent crosscheck must be available"),
      (reserve.get("controller_owns_reserve") is False,"LifeOS must not own reserve before event"),
      (control.get("write_performed") is False,"no pre-event battery write permitted"),
    ]
failed=[m for ok,m in checks if not ok]
if failed:
    for m in failed: print("PROOF_FAIL="+m)
    raise SystemExit(1)
print("POWERDOWN_LIVE_READINESS_PROOF=PASS")
PY

pass "HA REST telemetry recovered and Power Down safety trust rebuilt"
echo "RESULT=PASS_POWERDOWN_READY"
