#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/runtime_visibility.json')
try:
    d = json.loads(p.read_text()) if p.exists() else {"proxmox": {}}
    print("on" if d["proxmox"].get("reachable", False) else "off")
except Exception:
    print("off")
