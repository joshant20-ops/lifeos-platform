#!/usr/bin/env python3
import json
import sys
from pathlib import Path

DASHBOARD = Path("/config/execution_safety_dashboard.json")

def read_json(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

def get_value(data, key):
    overall = data.get("overall", {})
    queue = data.get("queue", {})
    policy = data.get("policy", {})

    mapping = {
        "rollup_status": overall.get("rollup_status", "unknown"),
        "alert_required": overall.get("alert_required", "unknown"),
        "alert_level": overall.get("alert_level", "unknown"),
        "reboot_survival_status": overall.get("reboot_survival_status", "unknown"),
        "active_queue_items": queue.get("active_queue_items", 0),
        "unsafe_active_queue_items": queue.get("unsafe_active_queue_items", 0),
        "quarantined_items_total": queue.get("quarantined_items_total", 0),
        "blocked_policy_violations": policy.get("blocked_policy_violations", 0),
        "proposal_count": policy.get("proposal_count", 0),
        "execution_log_entries": policy.get("execution_log_entries", 0),
    }

    if key in mapping:
        return mapping[key]

    if key.startswith("host:"):
        parts = key.split(":")
        if len(parts) != 3:
            return "unknown"

        _, host_id, field = parts

        for host in data.get("hosts", []):
            if host.get("host_id") == host_id:
                if field == "state":
                    return "READY" if host.get("allowed") else "BLOCKED"
                return host.get(field, "unknown")

        return "unknown"

    return "unknown"

def main():
    key = sys.argv[1] if len(sys.argv) > 1 else ""
    data = read_json(DASHBOARD)
    print(get_value(data, key))

if __name__ == "__main__":
    main()
