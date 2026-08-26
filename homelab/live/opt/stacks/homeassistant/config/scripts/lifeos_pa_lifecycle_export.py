#!/usr/bin/env python3
import json, sys
from pathlib import Path

base = Path("/config")
name = sys.argv[1] if len(sys.argv) > 1 else "summary"
path_map = {
    "summary": base / "pa_dashboard_summary.json",
    "active": base / "open_loops_active.json",
    "attention": base / "open_loops_attention.json",
    "awaiting": base / "open_loops_awaiting_confirmation.json",
    "overdue": base / "open_loops_overdue.json",
    "closed": base / "open_loops_recently_closed.json",
}

p = path_map.get(name, path_map["summary"])
try:
    data = json.loads(p.read_text())
except Exception:
    print("ERROR")
    raise SystemExit(0)

if name == "summary":
    print(data.get("status", "unknown").upper())
else:
    print(len(data) if isinstance(data, list) else 0)
