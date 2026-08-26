#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/multi_host_container_visibility.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"summary": {}}
    print(data.get("summary", {}).get("unhealthy", 0))
except Exception:
    print("0")
