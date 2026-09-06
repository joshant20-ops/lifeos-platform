#!/usr/bin/env python3
"""Live acceptance for the specialist Energy Opportunity API and PA projection."""
from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path("/home/joshan/lifeos-platform")
LIVE_ENERGY = Path("/mnt/docker-data/automation/repos/LifeOS-Energy")
HA_ROOT = Path("/opt/stacks/homeassistant/config")

def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if check and result.returncode:
        raise SystemExit(f"command failed: {args[0]} rc={result.returncode} {result.stderr[-500:]}")
    return result

def require(ok: bool, label: str) -> None:
    if not ok:
        raise SystemExit(f"ENERGY_OPPORTUNITY_ACCEPTANCE=FAIL\nFAILED={label}")
    print(label + "=PASS")

def api(path: str) -> dict:
    label = path.strip("/").replace("/", "_").upper()
    with urllib.request.urlopen("http://127.0.0.1:8110" + path, timeout=10) as response:
        require(response.status == 200, "API_HTTP_" + label)
        payload = json.load(response)
    require(isinstance(payload, dict), "API_OBJECT_" + label)
    return payload

containers = set(run(["docker", "ps", "--format", "{{.Names}}"]).stdout.splitlines())
for name in ("homeassistant", "lifeos-energy", "mosquitto", "predbat"):
    require(name in containers, "CONTAINER_" + name.upper().replace("-", "_"))

status = api("/api/status")
require(status.get("modules", {}).get("energy_opportunities") == "ready", "ENERGY_SPECIALIST_MODULE")
first = api("/api/energy/opportunities/current")
second = api("/api/energy/opportunities/current")
require(first.get("state") in {"clear", "attention", "unavailable"}, "OPPORTUNITY_STATE")
require(isinstance(first.get("opportunity_ids"), list), "OPPORTUNITY_IDS")
require(first.get("attention_id") == second.get("attention_id"), "CURRENT_REPLAY_STABLE_ID")
require(first.get("opportunity_ids") == second.get("opportunity_ids"), "CURRENT_REPLAY_DEDUPED_IDS")
require(len(first.get("opportunity_ids", [])) == len(set(first.get("opportunity_ids", []))), "CURRENT_IDS_UNIQUE")

require((LIVE_ENERGY / "app/services/opportunities.py").is_file(), "LIVE_SPECIALIST_SERVICE_SOURCE")
require((LIVE_ENERGY / "app/routers/opportunities.py").is_file(), "LIVE_SPECIALIST_API_SOURCE")

timer_state = run(["systemctl", "is-enabled", "lifeos-energy-opportunity-attention.timer"], False).stdout.strip()
require(timer_state != "enabled", "LEGACY_TIMER_RETIRED")
require(not Path("/etc/systemd/system/lifeos-energy-opportunity-attention.timer").exists(), "LEGACY_TIMER_FILE_RETIRED")
require(not Path("/etc/systemd/system/lifeos-energy-opportunity-attention.service").exists(), "LEGACY_SERVICE_FILE_RETIRED")
require(not (HA_ROOT / "lifeos_energy_opportunity_attention.json").exists(), "LEGACY_JSON_BRIDGE_RETIRED")

adapter = run(["docker", "exec", "homeassistant", "python3", "/config/scripts/lifeos_energy_attention_sensor.py"])
adapter_payload = json.loads(adapter.stdout)
require(adapter_payload.get("attention_id") == first.get("attention_id"), "HA_ADAPTER_IDENTITY")

registry_code = """import json
from pathlib import Path
d=json.loads(Path('/config/.storage/core.entity_registry').read_text())
for e in d.get('data',{}).get('entities',[]):
 if e.get('unique_id')=='lifeos_energy_opportunity_attention': print(e.get('entity_id',''))
"""
entity = run(["docker", "exec", "homeassistant", "python3", "-c", registry_code]).stdout.strip()
require(entity == "sensor.lifeos_energy_opportunity_attention", "HA_ENTITY_ID_STABLE")

attention_source = (ROOT / "homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml").read_text()
require("sensor.lifeos_energy_opportunity_attention" in attention_source, "COMMON_ATTENTION_INTEGRATION")

for name in ("homeassistant", "lifeos-energy"):
    health = run(["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", name]).stdout.strip()
    require(health in {"healthy", "running"}, name.upper().replace("-", "_") + "_HEALTH")

repo_status = run(["git", "-C", str(ROOT), "status", "--porcelain"]).stdout.strip()
head = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).stdout.strip()
origin = run(["git", "-C", str(ROOT), "rev-parse", "origin/main"]).stdout.strip()
require(not repo_status and head == origin, "CANONICAL_REPOSITORY_CLEAN")

print("CURRENT_STATE=" + str(first.get("state")))
print("CURRENT_COUNT=" + str(first.get("count")))
print("CURRENT_ATTENTION_ID=" + str(first.get("attention_id") or "none"))
print("ENERGY_AUTHORITY=lifeos-energy")
print("HA_ROLE=stable_attention_adapter")
print("NOTIFICATIONS_SENT=NO")
print("ENERGY_CONTROL_MUTATION=NO")
print("ENERGY_OPPORTUNITY_ACCEPTANCE=PASS")
