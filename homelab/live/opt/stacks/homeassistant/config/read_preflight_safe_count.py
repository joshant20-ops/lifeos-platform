#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/watchman_preflight_report.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"summary": {}}
    print(data.get("summary", {}).get("safe", 0))
except Exception:
    print("0")
