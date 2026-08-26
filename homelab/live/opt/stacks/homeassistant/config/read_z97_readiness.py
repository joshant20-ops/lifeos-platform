#!/usr/bin/env python3
import json
from pathlib import Path

p = Path('/config/host_readiness_status.json')

try:
    data = json.loads(p.read_text()) if p.exists() else {"hosts": []}
    host = next((h for h in data.get("hosts", []) if h.get("host_id") == "z97_vm_host"), {})
    attrs = {
        "lifecycle_state": host.get("lifecycle_state", "unknown"),
        "trust_state": host.get("trust_state", "unknown"),
        "boot_detected_at": host.get("boot_detected_at"),
        "elapsed_since_boot_seconds": host.get("elapsed_since_boot_seconds", 0),
        "grace_remaining_seconds": host.get("grace_remaining_seconds", 0),
        "last_check_at": host.get("last_check_at"),
        "next_check_due_at": host.get("next_check_due_at"),
        "blocking_reason": host.get("blocking_reason", "unknown"),
        "ping": host.get("checks", {}).get("ping", "unknown"),
        "ssh": host.get("checks", {}).get("ssh", "unknown"),
        "docker": host.get("checks", {}).get("docker", "unknown"),
        "metrics": host.get("checks", {}).get("metrics", "unknown"),
        "stability_hold": host.get("checks", {}).get("stability_hold", "unknown")
    }
    print(json.dumps({
        "state": host.get("lifecycle_state", "unknown"),
        "attributes": attrs
    }))
except Exception as exc:
    print(json.dumps({
        "state": "error",
        "attributes": {
            "blocking_reason": f"reader_script_error: {exc}"
        }
    }))
