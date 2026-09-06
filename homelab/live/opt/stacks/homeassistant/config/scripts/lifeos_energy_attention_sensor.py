#!/usr/bin/env python3
"""Stable HA entity adapter for the authoritative LifeOS Energy API."""
import json
from urllib.request import urlopen

try:
    with urlopen(
        'http://127.0.0.1:8110/api/energy/opportunities/current',
        timeout=10,
    ) as response:
        data = json.loads(response.read().decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('not_object')
except Exception:
    data = {
        'state': 'unavailable',
        'available': False,
        'count': 0,
        'attention_id': '',
        'opportunity_ids': [],
        'kind': 'energy_opportunity',
        'severity': 'info',
        'summary': 'LifeOS Energy opportunity API unavailable',
    }
print(json.dumps(data, separators=(',', ':'), sort_keys=True))
