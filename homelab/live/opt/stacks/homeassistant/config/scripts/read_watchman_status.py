#!/usr/bin/env python3
import json
import sys
from pathlib import Path

p = Path("/config/watchman_status_summary.json")
key = sys.argv[1] if len(sys.argv) > 1 else "status"
default = sys.argv[2] if len(sys.argv) > 2 else "unknown"

try:
    data = json.loads(p.read_text())
    value = data.get(key, default)
    if isinstance(value, bool):
        print(str(value).lower())
    else:
        print(value)
except Exception:
    print(default)
