#!/usr/bin/env python3
"""Read current+next Octopus import rates from HA and emit Energy Opportunities.
Detection only: no notifications or control side effects.
"""
from __future__ import annotations
import importlib.util,json,subprocess,sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('opportunities',ROOT/'energy/app/opportunities.py')
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
LEDGER=Path.home()/'.local/state/lifeos/energy-opportunities.json'
CURRENT=Path.home()/'.local/state/lifeos/current-energy-opportunities.json'

def de(code,*args): return subprocess.run(['docker','exec','homeassistant','python3','-c',code,*args],text=True,capture_output=True)
# Registry selects import current/next day rate events; export explicitly excluded.
code="""import json
d=json.load(open('/config/.storage/core.entity_registry'))
for x in d.get('data',{}).get('entities',[]):
 e=x.get('entity_id','')
 if e.startswith('event.octopus_energy_electricity_') and 'export' not in e and ('current_day_rates' in e or 'next_day_rates' in e): print(e)
"""
r=de(code)
if r.returncode: raise SystemExit(r.stderr)
ids=sorted(set(r.stdout.splitlines()))
if not ids: raise SystemExit('no Octopus import rate event entities')
slots={}
for eid in ids:
 q="""import json,sqlite3,sys
c=sqlite3.connect('/config/home-assistant_v2.db'); c.row_factory=sqlite3.Row
r=c.execute('''select sa.shared_attrs from states s join states_meta sm on sm.metadata_id=s.metadata_id left join state_attributes sa on sa.attributes_id=s.attributes_id where sm.entity_id=? order by s.state_id desc limit 1''',(sys.argv[1],)).fetchone()
a=json.loads((r['shared_attrs'] if r else None) or '{}')
print(json.dumps(a.get('rates',[]),separators=(',',':')))
"""
 x=de(q,eid)
 if x.returncode: raise SystemExit(x.stderr)
 for raw in json.loads(x.stdout):
  start=datetime.fromisoformat(raw['start']); end=datetime.fromisoformat(raw['end'])
  slots[start.isoformat()]=m.RateSlot(start,end,float(raw['value_inc_vat']))
now=datetime.now().astimezone()
opps=m.group_negative_import_slots(slots.values(),detected_at=now,source='home_assistant_octopus_rate_events')
CURRENT.parent.mkdir(parents=True,exist_ok=True)
CURRENT.write_text(json.dumps([m.asdict(x) for x in opps],indent=2,sort_keys=True)+'\n')
ledger=m.OpportunityLedger(LEDGER); unseen=ledger.unseen(opps)
print('ENERGY_OPPORTUNITY_DETECTION=PASS')
print('RATE_EVENT_ENTITIES='+str(len(ids)))
print('RATE_SLOTS='+str(len(slots)))
print('NEGATIVE_WINDOWS='+str(len(opps)))
print('UNSEEN_WINDOWS='+str(len(unseen)))
for x in opps:
 print('OPPORTUNITY='+json.dumps(m.asdict(x),sort_keys=True,separators=(',',':')))
print('CURRENT_FILE='+str(CURRENT))
print('LEDGER_FILE='+str(LEDGER))
print('NOTIFICATIONS_SENT=NO')
