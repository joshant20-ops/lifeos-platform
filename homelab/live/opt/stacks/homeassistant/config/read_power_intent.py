#!/usr/bin/env python3
import json
from pathlib import Path

INTENT_PATH = Path("/config/power_intent.json")

try:
    data = json.loads(INTENT_PATH.read_text()) if INTENT_PATH.exists() else {"hosts": []}
    hosts = {h.get("host_id"): h.get("intended_power", "unknown") for h in data.get("hosts", [])}

    payload = {
        "state": "loaded",
        "attributes": {
            "docker_host": hosts.get("docker_host", "unknown"),
            "z97_vm_host": hosts.get("z97_vm_host", "unknown"),
            "pi3_oob_controller": hosts.get("pi3_oob_controller", "unknown")
        }
    }
    print(json.dumps(payload))
except Exception as e:
    print(json.dumps({
        "state": "error",
        "attributes": {
            "error": str(e),
            "docker_host": "unknown",
            "z97_vm_host": "unknown",
            "pi3_oob_controller": "unknown"
        }
    }))
