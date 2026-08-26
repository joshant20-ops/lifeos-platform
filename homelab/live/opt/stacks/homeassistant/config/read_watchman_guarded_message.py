#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/watchman_guarded_status.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {}
    print(data.get("message", "unknown"))
except Exception:
    print("error")
