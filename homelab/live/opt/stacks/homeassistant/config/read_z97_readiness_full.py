#!/usr/bin/env python3
import json
from pathlib import Path

p = Path('/config/host_readiness_status.json')

try:
    data = json.loads(p.read_text()) if p.exists() else {"hosts": []}
    host = next((h for h in data.get("hosts", []) if h.get("host_id") == "z97_vm_host"), {})

    def g(key, default="unknown"):
        return str(host.get(key, default))

    def c(key):
        return str(host.get("checks", {}).get(key, "unknown"))

    attrs = {
        "lifecycle_state": g("lifecycle_state"),
        "trust_state": g("trust_state"),
        "blocking_reason": g("blocking_reason"),
        "grace_remaining": str(host.get("grace_remaining_seconds", 0)),
        "ping": c("ping"),
        "ssh": c("ssh"),
        "docker": c("docker"),
        "metrics": c("metrics"),
        "stability_hold": c("stability_hold")
    }

    print(json.dumps({
        "state": attrs["lifecycle_state"],
        "attributes": attrs
    }))

except Exception as e:
    print(json.dumps({
        "state": "error",
        "attributes": {"error": str(e)}
    }))
