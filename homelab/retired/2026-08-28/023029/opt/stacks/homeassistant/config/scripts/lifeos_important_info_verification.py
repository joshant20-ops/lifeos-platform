#!/usr/bin/env python3
import json, sys
from pathlib import Path

p = Path('/config/important_information_verification_summary.json')

try:
    data = json.loads(p.read_text())
except Exception:
    print(0)
    raise SystemExit(0)

field = sys.argv[1] if len(sys.argv) > 1 else 'needs_review_count'

if field == 'status':
    print(data.get('status','unknown'))
else:
    print(data.get('counts',{}).get(field, data.get(field,0)))
