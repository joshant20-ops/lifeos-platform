#!/usr/bin/env python3
import json
import sys
from pathlib import Path

STATE_CANDIDATES = [
    Path("/config/lifeos_playbook_detail.json"),
    Path("/opt/stacks/homeassistant/config/lifeos_playbook_detail.json"),
]

MAX_LEN = 240

def read():
    for state in STATE_CANDIDATES:
        try:
            if state.exists():
                return json.loads(state.read_text())
        except Exception:
            pass
    return {}

def one_line(lines):
    if not lines:
        return "none"
    text = " ; ".join(str(x) for x in lines[:3])
    return text[:MAX_LEN]

def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "summary"
    d = read()
    c = d.get("counts", {})

    values = {
        "summary": str(d.get("summary", "unknown"))[:MAX_LEN],
        "history_count": c.get("history", 0),
        "active_count": c.get("active", 0),
        "active_queue_count": c.get("active_queue", 0),
        "queue_log_entries": c.get("queue_log_entries", 0),
        "quarantine_count": c.get("quarantine", 0),
        "execution_log_entries": c.get("executions", 0),
        "total_pages": c.get("total_pages", 0),
        "last_action": str(d.get("last_action", "none"))[:MAX_LEN],
        "active_detail": one_line(d.get("active_lines", [])),
        "history_detail": one_line(d.get("history_lines", [])),
        "queue_detail": one_line(d.get("queue_lines", [])),
    }

    print(values.get(key, "unknown"))

if __name__ == "__main__":
    main()
