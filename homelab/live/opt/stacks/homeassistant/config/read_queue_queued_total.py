#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/queue_risk_snapshot.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"summary": {}}
    print(data.get("summary", {}).get("queued_total", 0))
except Exception:
    print("0")
