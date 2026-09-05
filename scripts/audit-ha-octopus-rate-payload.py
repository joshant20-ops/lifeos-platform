#!/usr/bin/env python3
"""Read-only, sanitized inspection of HA Octopus rate event state/attribute shape."""
import json,subprocess

def de(cmd): return subprocess.run(['docker','exec','homeassistant',*cmd],text=True,capture_output=True)
r=de(['python3','-c',"import json;d=json.load(open('/config/.storage/core.entity_registry'));print('\\n'.join(x.get('entity_id','') for x in d.get('data',{}).get('entities',[]) if x.get('entity_id','').startswith('event.octopus_energy_electricity_') and 'export' not in x.get('entity_id','') and ('current_day_rates' in x.get('entity_id','') or 'next_day_rates' in x.get('entity_id',''))))"])
if r.returncode: raise SystemExit(r.stderr)
ids=sorted(set(r.stdout.splitlines()))
print('RATE_EVENT_ENTITIES='+str(len(ids)))
for eid in ids:
    code="""import json,sqlite3,sys
p='/config/home-assistant_v2.db'; eid=sys.argv[1]
c=sqlite3.connect(p); c.row_factory=sqlite3.Row
q='''select sm.entity_id,s.state,sa.shared_attrs from states s join states_meta sm on sm.metadata_id=s.metadata_id left join state_attributes sa on sa.attributes_id=s.attributes_id where sm.entity_id=? order by s.state_id desc limit 1'''
r=c.execute(q,(eid,)).fetchone()
if not r: print(json.dumps({'entity_id':eid,'present':False})); raise SystemExit
attrs=json.loads(r['shared_attrs'] or '{}')
def shape(v):
    if isinstance(v,dict): return {'type':'dict','keys':sorted(v.keys())}
    if isinstance(v,list):
        return {'type':'list','length':len(v),'item':shape(v[0]) if v else None}
    return {'type':type(v).__name__}
print(json.dumps({'entity_id':eid,'present':True,'state_type':type(r['state']).__name__,'attributes':{k:shape(v) for k,v in attrs.items()}},sort_keys=True))
"""
    x=de(['python3','-c',code,eid])
    if x.returncode: raise SystemExit(x.stderr)
    print(x.stdout.strip())
print('RATE_PAYLOAD_AUDIT=PASS')
print('VALUES_EMITTED=NO')
