#!/usr/bin/env python3
import json, sys
from pathlib import Path
from datetime import datetime, UTC

REQ = Path("/config/lifeos_action_requests.json")

ALLOWED = {
    "request_review_pending",
    "request_clear_quarantine",
    "request_run_watchman_pipeline",
}

def now():
    return datetime.now(UTC).isoformat()

def read():
    try:
        return json.loads(REQ.read_text()) if REQ.exists() else {"requests": []}
    except Exception:
        return {"requests": []}

def write(data):
    REQ.write_text(json.dumps(data, indent=2) + "\n")

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ALLOWED:
        print("REJECTED_UNKNOWN_ACTION")
        return

    data = read()
    data.setdefault("requests", [])
    data["requests"].append({
        "requested_at": now(),
        "action": action,
        "status": "requested_from_ha",
        "source": "home_assistant_lovelace",
    })
    write(data)
    print(f"REQUESTED:{action}")

if __name__ == "__main__":
    main()
