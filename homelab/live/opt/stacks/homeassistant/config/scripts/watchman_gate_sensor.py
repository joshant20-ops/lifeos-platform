#!/usr/bin/env python3
import json
import sys
from pathlib import Path

host_id = sys.argv[1]
p = Path("/config/watchman_gate_status.json")

try:
    data = json.loads(p.read_text())
    host = next(h for h in data["hosts"] if h["host_id"] == host_id)
    print("READY" if host.get("allowed") else "BLOCKED")
except Exception:
    print("unknown")
