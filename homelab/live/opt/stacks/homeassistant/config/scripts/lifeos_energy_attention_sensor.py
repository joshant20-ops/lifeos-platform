#!/usr/bin/env python3
"""Home Assistant command_line reader for the local Energy Opportunity projection."""
import json
from pathlib import Path

p = Path('/config/lifeos_energy_opportunity_attention.json')
try:
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise ValueError('not_object')
except Exception:
    data = {
        'state': 'unavailable',
        'count': 0,
        'attention_id': '',
        'opportunity_ids': [],
        'kind': 'energy_opportunity',
        'severity': 'info',
        'summary': 'Energy opportunity projection unavailable',
    }
print(json.dumps(data, separators=(',', ':'), sort_keys=True))
