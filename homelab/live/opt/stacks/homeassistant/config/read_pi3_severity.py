#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/host_interpretation_status.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"hosts": []}
    host = next((h for h in data.get("hosts", []) if h.get("host_id") == "pi3_oob_controller"), {})
    print(host.get("severity", "unknown"))
except Exception:
    print("unknown")
