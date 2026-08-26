#!/usr/bin/env python3
import json, sys
from pathlib import Path

BASE = Path("/config")

FILES = {
    "proposals": BASE / "playbook_pages.json",
    "queue": BASE / "watchman_queue.json",
    "quarantine": BASE / "watchman_quarantine.json",
    "rollup": BASE / "execution_safety_rollup.json",
}

def read(p, default):
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except Exception:
        return default

def main():
    key = sys.argv[1] if len(sys.argv) > 1 else ""

    ps = read(FILES["proposals"], {"proposals":[]}).get("proposals", [])
    qs = read(FILES["queue"], {"items":[]}).get("items", [])
    qi = read(FILES["quarantine"], {"items":[]}).get("items", [])
    roll = read(FILES["rollup"], {})

    pending = [p for p in ps if p.get("status") == "pending"]
    blocked = roll.get("counts", {}).get("blocked_policy_violations", 0)

    items = []

    if pending:
        items.append(f"{len(pending)} pending approvals")

    if qi:
        items.append(f"{len(qi)} quarantined items")

    if blocked:
        items.append(f"{blocked} policy blocks")

    if not items:
        summary = "No human action required"
    else:
        summary = " | ".join(items)

    vals = {
        "human_action_count": len(pending) + len(qi) + blocked,
        "human_action_summary": summary,
    }

    print(vals.get(key, "unknown"))

if __name__ == "__main__":
    main()
