#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/multi_host_container_visibility.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"hosts": []}
    for h in data.get("hosts", []):
        if h.get("host_id") == "docker_host":
            print(h.get("state", "unknown"))
            raise SystemExit
    print("unknown")
except Exception:
    print("unknown")
