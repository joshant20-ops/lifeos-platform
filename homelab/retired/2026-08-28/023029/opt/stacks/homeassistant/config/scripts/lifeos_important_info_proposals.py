#!/usr/bin/env python3
import json, sys
from pathlib import Path

p = Path('/config/important_information_proposal_summary.json')
try:
    data = json.loads(p.read_text())
except Exception:
    print(0)
    raise SystemExit(0)

field = sys.argv[1] if len(sys.argv) > 1 else 'pending_count'
print(data.get(field, 0))
