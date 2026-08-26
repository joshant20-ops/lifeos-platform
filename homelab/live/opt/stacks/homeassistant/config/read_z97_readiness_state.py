#!/usr/bin/env python3
import json
from pathlib import Path

p = Path('/config/host_readiness_status.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"hosts": []}
    host = next((h for h in data.get("hosts", []) if h.get("host_id") == "z97_vm_host"), {})
    print(host.get("lifecycle_state", "unknown"))
except Exception:
    print("error")
