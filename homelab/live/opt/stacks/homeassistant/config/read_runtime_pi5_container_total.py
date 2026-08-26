#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/runtime_visibility.json')
try:
    d = json.loads(p.read_text()) if p.exists() else {"summary": {}}
    print(d["summary"].get("pi5_container_total", 0))
except Exception:
    print("0")
