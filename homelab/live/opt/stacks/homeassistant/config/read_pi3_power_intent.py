#!/usr/bin/env python3
import json
from pathlib import Path

p = Path('/config/power_intent.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"hosts": []}
    host = next((h for h in data.get("hosts", []) if h.get("host_id") == "pi3_oob_controller"), {})
    print(host.get("intended_power", "unknown"))
except Exception:
    print("error")
