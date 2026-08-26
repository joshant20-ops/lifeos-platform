#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/host_interpretation_status.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"hosts": []}
    host = next((h for h in data.get("hosts", []) if h.get("host_id") == "docker_host"), {})
    print(str(host.get("action_required", False)).lower())
except Exception:
    print("false")
