#!/usr/bin/env python3
"""Read-only Wave A implementation-gap audit.

Emits only structural facts needed to choose the smallest safe integration path.
No states, payloads, secrets, full commands or template bodies are emitted.
"""
from __future__ import annotations
import json,re,subprocess
from pathlib import Path

OUT=Path.home()/'.local/state/lifeos/wave-a-implementation-gap.json'

def run(args): return subprocess.run(args,text=True,capture_output=True)
def fail(msg):
    print('WAVE_A_IMPLEMENTATION_GAP=FAIL'); print('DETAIL='+msg[:1000].replace('\n',' | ')); raise SystemExit(1)
ps=run(['docker','ps','--format','{{.Names}}'])
if ps.returncode: fail('docker ps failed')
cs=set(ps.stdout.splitlines()); ha='homeassistant' if 'homeassistant' in cs else 'home-assistant' if 'home-assistant' in cs else None
if not ha or 'lifeos-energy' not in cs: fail('required containers missing')

# Inspect relevant HA packages. Entity references are extracted from templates,
# but template bodies and command arguments remain private.
parser=r'''
import json,pathlib,yaml,re,shlex
files=['/config/packages/lifeos_attention.yaml','/config/packages/lifeos_actions.yaml','/config/packages/lifeos_energy.yaml','/config/packages/lifeos_pa.yaml','/config/packages/lifeos_pa_lifecycle.yaml']
allow={'name','unique_id','alias','service','event_type','entity_id','topic','state_topic','command_topic','json_attributes_topic'}
out={}
def walk(x,path,a):
  if isinstance(x,dict):
    for k,v in x.items():
      p=path+[str(k)]; a['paths'].add('.'.join(p))
      if str(k) in allow and isinstance(v,str) and len(v)<160 and '{{' not in v and '{%' not in v and '://' not in v:
        a['ids'].append({'path':'.'.join(p),'value':v})
      if isinstance(v,str):
        for eid in re.findall(r'\b(?:sensor|binary_sensor|event|input_[a-z_]+|button|script)\.[a-z0-9_]+\b',v.lower()): a['entity_refs'].add(eid)
        if str(k) in ('command','shell_command'):
          try:
            parts=shlex.split(v); a['command_basenames'].add(pathlib.Path(parts[0]).name if parts else '')
          except Exception: pass
      walk(v,p,a)
  elif isinstance(x,list):
    for v in x[:100]: walk(v,path+['[]'],a)
for f in files:
 p=pathlib.Path(f); a={'exists':p.exists(),'paths':set(),'ids':[],'entity_refs':set(),'command_basenames':set()}
 if p.exists():
  raw=p.read_text(); d=yaml.safe_load(raw) or {}; walk(d,[],a)
 a['paths']=sorted(a['paths']); a['entity_refs']=sorted(a['entity_refs']); a['command_basenames']=sorted(x for x in a['command_basenames'] if x); out[f]=a
print(json.dumps(out,sort_keys=True))
'''
cp=run(['docker','exec',ha,'python3','-c',parser])
if cp.returncode: fail('HA package parser failed')
ha_struct=json.loads(cp.stdout)

# HA mount destinations/sources limited to LifeOS/config paths; no env/secrets.
di=run(['docker','inspect',ha])
if di.returncode: fail('HA inspect failed')
obj=json.loads(di.stdout)[0]
mounts=[]
for m in obj.get('Mounts',[]):
    src=str(m.get('Source','')); dst=str(m.get('Destination',''))
    if dst.startswith('/config') or 'lifeos' in (src+dst).lower(): mounts.append({'source':src,'destination':dst,'rw':bool(m.get('RW'))})

# Inspect LifeOS Energy filesystem names and source symbol names only.
probe=r'''
import os,ast,json
roots=['/app','/opt/lifeos-energy']
files=[]; symbols=[]
for root in roots:
 if not os.path.isdir(root): continue
 for dp,ds,fs in os.walk(root):
  ds[:]=[d for d in ds if d not in ('__pycache__','.git','venv','.venv')]
  for fn in fs:
   if not fn.endswith(('.py','.json','.yaml','.yml')): continue
   p=os.path.join(dp,fn); files.append(p)
   if fn.endswith('.py'):
    try:
     t=ast.parse(open(p,errors='ignore').read())
     for n in ast.walk(t):
      if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and any(k in n.name.lower() for k in ('opportun','negative','event','ledger','dedup','notify','attention')):
       symbols.append(n.name)
    except Exception: pass
print(json.dumps({'files':sorted(files)[:300],'symbols':sorted(set(symbols))[:300]}))
'''
ep=run(['docker','exec','lifeos-energy','python3','-c',probe])
if ep.returncode: fail('energy structural probe failed')
energy=json.loads(ep.stdout)
report={'schema_version':2,'mode':'read_only_implementation_gap','ha':ha_struct,'ha_mounts':mounts,'energy':energy,'states_emitted':False,'payloads_emitted':False,'secrets_emitted':False,'commands_emitted':False,'mutation_performed':False}
OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print('WAVE_A_IMPLEMENTATION_GAP=PASS')
for f,a in ha_struct.items():
 print('HA_FILE='+f+' EXISTS='+str(a['exists']).upper())
 for x in a['ids']: print('HA_ID='+x['path']+'='+x['value'])
 for x in a['entity_refs']: print('HA_ENTITY_REF='+f+'='+x)
 for x in a['command_basenames']: print('HA_COMMAND_BASENAME='+f+'='+x)
for m in mounts: print('HA_MOUNT='+m['source']+' -> '+m['destination']+' RW='+str(m['rw']).upper())
print('ENERGY_FILES='+str(len(energy['files'])))
for x in energy['files']: print('ENERGY_FILE='+x)
for x in energy['symbols']: print('ENERGY_SYMBOL='+x)
print('STATES_EMITTED=NO'); print('PAYLOADS_EMITTED=NO'); print('SECRETS_EMITTED=NO'); print('COMMANDS_EMITTED=NO'); print('MUTATION_PERFORMED=NO')
