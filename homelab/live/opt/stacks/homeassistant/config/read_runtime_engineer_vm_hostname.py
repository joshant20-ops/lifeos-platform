#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/runtime_visibility.json')
try:
    d = json.loads(p.read_text()) if p.exists() else {"engineer_vm": {}}
    print(d["engineer_vm"].get("hostname") or "unknown")
except Exception:
    print("unknown")
