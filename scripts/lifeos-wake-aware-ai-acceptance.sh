#!/usr/bin/env bash
set -Eeuo pipefail
BASE_URL=http://127.0.0.1:18114
STARTED_AT=$(date --iso-8601=seconds)
CLEANUP_NEEDED=0
tower_state() { timeout 6 mosquitto_sub -h 127.0.0.1 -C 1 -t lifeos/tower/state; }
assert_off() {
  local state; state=$(tower_state)
  python3 - "$state" <<'PY'
import json,sys
v=json.loads(sys.argv[1]); assert v.get("state")=="OFF" and v.get("accessible") is False,v
PY
}
cleanup() { if [[ "$CLEANUP_NEEDED" == 1 ]]; then mosquitto_pub -h 127.0.0.1 -t lifeos/tower/power/set -m OFF >/dev/null 2>&1 || true; fi; }
trap cleanup EXIT
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
lifeos-secret exec homeassistant.long_lived_access_token HA_TOKEN python3 -c '
import os,urllib.request
h={"Authorization":"Bearer "+os.environ["HA_TOKEN"],"Accept":"application/json"}
base="http://127.0.0.1:8123/api/states/"
for entity in ("predbat.status","sensor.lifeos_grid_import_power","sensor.predbat_enphase_5731818_pv_power"):
    with urllib.request.urlopen(urllib.request.Request(base+entity,headers=h),timeout=10) as r: assert r.status==200
print("LOCAL_HA_LIFEOS=PASS")
'
echo 'LOCAL_AGENT_ENERGY=PASS'
CLEANUP_NEEDED=1
mosquitto_pub -h 127.0.0.1 -t lifeos/tower/power/set -m OFF
off=0
for _ in $(seq 1 120); do
  if state=$(tower_state 2>/dev/null) && python3 - "$state" <<'PY' >/dev/null 2>&1
import json,sys
raise SystemExit(0 if json.loads(sys.argv[1]).get("state")=="OFF" else 1)
PY
  then off=1; break; fi
  sleep 2
done
test "$off" -eq 1; assert_off
health=$(curl -fsS --max-time 5 "$BASE_URL/health")
python3 - "$health" <<'PY'
import json,sys
v=json.loads(sys.argv[1]); assert v["status"]=="degraded" and v["compute"]=="asleep",v
assert v["degraded_reason"]=="COMPUTE_ASLEEP" and v["tower_accessible"] is False,v
print("HEALTH_NO_WAKE=PASS")
PY
sleep 3; assert_off
echo 'ENDPOINT_REACHABLE_TOWER_OFF=PASS'
python3 - "$BASE_URL" <<'PY'
import concurrent.futures,json,pathlib,sys,urllib.request
base=sys.argv[1]
def infer(label):
    p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request "+label,"stream":False}
    q=urllib.request.Request(base+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(q,timeout=1500) as r: v=json.load(r)
    assert isinstance(v.get("response"),str) and v["response"].strip(),v
    return v["response"]
def broker_infer():
    token=pathlib.Path.home().joinpath(".config/lifeos/ai-broker.token").read_text().strip()
    p={"model":"lifeos-local-only-normal","messages":[{"role":"user","content":"Call report_test_value with value ENDPOINT_BROKER_WAKE_OK. Do not answer normally."}],"stream":False,"tools":[{"type":"function","function":{"name":"report_test_value","description":"Report a harmless endpoint acceptance value.","parameters":{"type":"object","properties":{"value":{"type":"string"}},"required":["value"]}}}],"tool_choice":"required"}
    q=urllib.request.Request("http://127.0.0.1:8790/v1/chat/completions",data=json.dumps(p).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+token},method="POST")
    with urllib.request.urlopen(q,timeout=1500) as r: v=json.load(r)
    calls=v["choices"][0]["message"].get("tool_calls") or []
    assert any(c.get("function",{}).get("name")=="report_test_value" for c in calls),v
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
    futures=[ex.submit(infer,"cold-A"),ex.submit(infer,"cold-B"),ex.submit(broker_infer)]
    [f.result(timeout=1600) for f in futures]
print("CONCURRENT_DIRECT_AND_BROKER_REQUESTS=PASS")
PY
ready=0
for _ in $(seq 1 120); do
  if state=$(tower_state 2>/dev/null) && python3 - "$state" <<'PY' >/dev/null 2>&1
import json,sys
raise SystemExit(0 if json.loads(sys.argv[1]).get("accessible") is True else 1)
PY
  then if curl -fsS --max-time 3 http://192.168.0.201:11434/api/tags >/dev/null; then ready=1; break; fi; fi
  sleep 2
done
test "$ready" -eq 1; echo 'TOWER_ACCESSIBLE_AND_OLLAMA_READY=PASS'
wakes=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=LEASE$' || true)
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=LEASE$' || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
mosquitto_pub -h 127.0.0.1 -t lifeos/tower/power/set -m OFF
stopped=0
for _ in $(seq 1 120); do
  if state=$(tower_state 2>/dev/null) && python3 - "$state" <<'PY' >/dev/null 2>&1
import json,sys
raise SystemExit(0 if json.loads(sys.argv[1]).get("state")=="OFF" else 1)
PY
  then stopped=1; break; fi
  sleep 2
done
test "$stopped" -eq 1; CLEANUP_NEEDED=0
echo 'TOWER_OFF_AFTER_ACCEPTANCE=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
