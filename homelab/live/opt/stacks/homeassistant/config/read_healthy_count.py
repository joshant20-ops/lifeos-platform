#!/usr/bin/env python3
import json
from pathlib import Path
p = Path('/config/action_board_status.json')
try:
    data = json.loads(p.read_text()) if p.exists() else {"summary": {}}
    print(data.get("summary", {}).get("healthy_count", 0))
except Exception:
    print("0")
