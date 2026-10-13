#!/usr/bin/env bash
set -Eeuo pipefail
BASE_URL=http://ai.lan:18114
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
STARTED_AT=$(date --iso-8601=seconds)
tower_state() { timeout 6 mosquitto_sub -h 127.0.0.1 -C 1 -t lifeos/tower/state; }
assert_service_unavailable() {
  local state
  state=$(tower_state)
  python3 - "$state" <<'PY'
import json,sys
v=json.loads(sys.argv[1])
assert v.get("accessible") is False, v
assert v.get("physical_power") == "UNKNOWN", v
print("TOWER_ACCESS_UNAVAILABLE=PASS")
print("PHYSICAL_POWER=UNKNOWN (recorded; not a gate)")
PY
  python3 - <<'PY'
import socket
try:
    socket.create_connection(("192.168.0.201",22),timeout=3)
except OSError:
    print("TOWER_SSH_UNAVAILABLE=PASS")
else:
    raise SystemExit("Tower SSH is reachable; cold-start precondition is not met")
PY
  if curl -fsS --max-time 3 http://192.168.0.201:11434/api/tags >/dev/null 2>&1; then
    echo 'Ollama is reachable; cold-start precondition is not met' >&2
    return 1
  fi
  echo 'OLLAMA_UNAVAILABLE=PASS'
}
assert_no_active_leases() {
  local retained
  retained=$(timeout 5 mosquitto_sub -h 127.0.0.1 -v -W 3 -t 'lifeos/tower/lease/+' 2>/dev/null || true)
  python3 - "$retained" <<'PY'
import json,sys,time
now=int(time.time())
active=[]
for line in sys.argv[1].splitlines():
    topic,sep,raw=line.partition(" ")
    if not sep: continue
    try: value=json.loads(raw)
    except ValueError as exc: raise SystemExit(f"invalid retained Tower lease on {topic}") from exc
    if value.get("state")=="active" and int(value.get("expires_at") or 0)>now:
        active.append(topic)
if active: raise SystemExit("active inference/wake leases present: "+", ".join(active))
print("NO_ACTIVE_INFERENCE_WAKE_LEASE=PASS")
PY
}
assert_cold_precondition() {
  assert_service_unavailable
  assert_no_active_leases
}
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
pi_ip=$(ip -4 route get 1.1.1.1 | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
dns_ip=$(getent ahostsv4 ai.lan | awk 'NR==1 {print $1}')
test -n "$pi_ip" && test "$dns_ip" = "$pi_ip"
echo "STABLE_AI_DNS=ai.lan->$pi_ip PASS"
echo 'LOCAL_AGENT_ENERGY=PASS'
assert_cold_precondition
health=$(curl -fsS --max-time 5 "$BASE_URL/health")
python3 - "$health" <<'PY'
import json,sys
v=json.loads(sys.argv[1])
assert v.get("status")=="degraded" and v.get("compute")=="asleep",v
assert v.get("degraded_reason")=="COMPUTE_ASLEEP",v
assert v.get("tower_accessible") is False and v.get("ollama_ready") is False,v
print("HEALTH_NO_WAKE=PASS")
PY
curl -fsS --max-time 5 "$BASE_URL/v1/models" >/dev/null
curl -fsS --max-time 5 "$BASE_URL/api/tags" >/dev/null
curl -fsS --max-time 5 "$BASE_URL/api/ps" >/dev/null
sleep 3
assert_cold_precondition
gateway_log="$XDG_RUNTIME_DIR/lifeos-openhands-local-ai.log"
test -r "$gateway_log"
passive_wakes=$(grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE
test "$passive_wakes" -eq 0
echo 'PASSIVE_STATUS_AND_MODEL_DISCOVERY_NO_WAKE=PASS'
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
print("ORIGINAL_COLD_INFERENCE_AND_CONCURRENCY=PASS")
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
wakes=$(grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
 "$gateway_log" || true)
test "$passive_wakes" -eq 0
echo 'PASSIVE_STATUS_AND_MODEL_DISCOVERY_NO_WAKE=PASS'
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
print("ORIGINAL_COLD_INFERENCE_AND_CONCURRENCY=PASS")
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
wakes=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
 "$gateway_log" || true)
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
 "$gateway_log" || true)
test "$passive_wakes" -eq 0
echo 'PASSIVE_STATUS_AND_MODEL_DISCOVERY_NO_WAKE=PASS'
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
print("ORIGINAL_COLD_INFERENCE_AND_CONCURRENCY=PASS")
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
wakes=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
 "$gateway_log" || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
 "$gateway_log" || true)
test "$passive_wakes" -eq 0
echo 'PASSIVE_STATUS_AND_MODEL_DISCOVERY_NO_WAKE=PASS'
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
print("ORIGINAL_COLD_INFERENCE_AND_CONCURRENCY=PASS")
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
wakes=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
 "$gateway_log" || true)
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
 "$gateway_log" || true)
test "$passive_wakes" -eq 0
echo 'PASSIVE_STATUS_AND_MODEL_DISCOVERY_NO_WAKE=PASS'
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
print("ORIGINAL_COLD_INFERENCE_AND_CONCURRENCY=PASS")
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
wakes=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes" -eq 1; echo 'COALESCED_LOGICAL_WAKE=PASS'
python3 - "$BASE_URL" <<'PY'
import json,sys,urllib.request
p={"model":"gpt-oss:20b","prompt":"Reply with READY. Request warm.","stream":False}
q=urllib.request.Request(sys.argv[1]+"/api/generate",data=json.dumps(p).encode(),headers={"Content-Type":"application/json"},method="POST")
with urllib.request.urlopen(q,timeout=900) as r: v=json.load(r)
assert isinstance(v.get("response"),str) and v["response"].strip(),v
print("WARM_INFERENCE=PASS")
PY
wakes_after=$(journalctl --user -u lifeos-openhands-local-ai.service --since "$STARTED_AT" -o cat --no-pager | grep -c '^TOWER_WAKE_REQUEST=CONTROLLER_LEASE$' || true)
test "$wakes_after" -eq "$wakes"; echo 'NO_SECOND_WAKE=PASS'
systemctl is-active --quiet lifeos-autonomous-agent.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service
curl -fsS --max-time 10 http://127.0.0.1:8110/api/energy/current >/dev/null
echo 'LOCAL_LIFEOS_HA_UNAFFECTED=PASS'
echo 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS'
