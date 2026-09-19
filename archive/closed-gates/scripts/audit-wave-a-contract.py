#!/usr/bin/env python3
"""Structural-only Wave A contract inspection against the live HA container.

This intentionally emits only schema/key paths, component names, entity ids and
MQTT topic names. It never emits template bodies, shell commands, states,
attributes, secrets, tokens, URLs, device identifiers or message payloads.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

FILES = [
    "/config/packages/lifeos_attention.yaml",
    "/config/packages/lifeos_pa.yaml",
    "/config/packages/lifeos_pa_lifecycle.yaml",
    "/config/packages/lifeos_actions.yaml",
    "/config/packages/lifeos_energy.yaml",
]
OUT = Path.home() / ".local/state/lifeos/wave-a-contract-audit.json"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True)


def fail(msg: str) -> None:
    print("WAVE_A_CONTRACT_AUDIT=FAIL")
    print("DETAIL=" + msg.replace("\n", " | ")[:2000])
    raise SystemExit(1)

ps = run(["docker", "ps", "--format", "{{.Names}}"])
if ps.returncode:
    fail("docker ps failed")
containers = set(ps.stdout.splitlines())
ha = "homeassistant" if "homeassistant" in containers else "home-assistant" if "home-assistant" in containers else None
if not ha:
    fail("Home Assistant container missing")

# Execute the parser inside HA so we use its YAML loader. The parser itself
# returns only a deliberately allow-listed structural projection.
parser = r'''
import hashlib,json,pathlib,yaml
files=json.loads(__import__('os').environ['WAVE_A_FILES'])
SAFE_SCALAR_KEYS={'name','unique_id','object_id','state_topic','json_attributes_topic','command_topic','availability_topic','event_type','alias','service','entity_id','topic'}
SENSITIVE_TOKENS=('token','secret','password','key','url','host','ip','device_id','user','person','phone','email')

def safe_value(key,value):
    lk=str(key).lower()
    if any(x in lk for x in SENSITIVE_TOKENS): return None
    if key not in SAFE_SCALAR_KEYS: return None
    if not isinstance(value,(str,int,float,bool)) or value is None: return None
    s=str(value)
    if len(s)>180: return None
    # Never emit templates/commands/payloads even if nested under a safe-looking key.
    low=s.lower()
    if '{{' in s or '{%' in s or 'curl ' in low or 'python ' in low or 'bash ' in low or 'payload' in low: return None
    return value

def walk(obj,path,out,depth=0):
    if depth>12: return
    if isinstance(obj,dict):
        for k,v in obj.items():
            ks=str(k)
            p=path+[ks]
            out['key_paths'].add('.'.join(p))
            sv=safe_value(ks,v)
            if sv is not None:
                out['safe_scalars'].append({'path':'.'.join(p),'value':sv})
            walk(v,p,out,depth+1)
    elif isinstance(obj,list):
        for v in obj[:100]: walk(v,path+['[]'],out,depth+1)

result={}
for f in files:
    p=pathlib.Path(f)
    item={'exists':p.exists()}
    if p.exists():
        raw=p.read_bytes()
        item.update({'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        try:
            data=yaml.safe_load(raw) or {}
            out={'key_paths':set(),'safe_scalars':[]}
            walk(data,[],out)
            item['top_level_keys']=sorted(map(str,data.keys())) if isinstance(data,dict) else [type(data).__name__]
            item['key_paths']=sorted(out['key_paths'])[:3000]
            # stable de-dup, retaining structural context
            seen=set(); vals=[]
            for x in out['safe_scalars']:
                t=(x['path'],str(x['value']))
                if t not in seen:
                    seen.add(t); vals.append(x)
            item['safe_scalars']=vals[:1000]
        except Exception as e:
            item['parse_error_type']=type(e).__name__
    result[f]=item
print(json.dumps(result,sort_keys=True))
'''
cp = run([
    "docker", "exec", "-e", "WAVE_A_FILES=" + json.dumps(FILES), ha,
    "python3", "-c", parser,
])
if cp.returncode:
    fail("HA structural parser failed: " + cp.stderr[-1000:])
try:
    files = json.loads(cp.stdout)
except json.JSONDecodeError:
    fail("HA structural parser returned invalid JSON")

report = {
    "schema_version": 1,
    "mode": "read_only_structural_contract_audit",
    "home_assistant_container": ha,
    "files": files,
    "states_emitted": False,
    "template_bodies_emitted": False,
    "commands_emitted": False,
    "secrets_emitted": False,
    "mutation_performed": False,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

print("WAVE_A_CONTRACT_AUDIT=PASS")
for f,item in files.items():
    print(f"FILE={f} EXISTS={str(item.get('exists')).upper()} SHA256={item.get('sha256','none')} SIZE={item.get('size',0)}")
    print("TOP_LEVEL=" + ",".join(item.get("top_level_keys", [])))
    print("SAFE_SCALARS=" + str(len(item.get("safe_scalars", []))))
print("STATES_EMITTED=NO")
print("TEMPLATE_BODIES_EMITTED=NO")
print("COMMANDS_EMITTED=NO")
print("SECRETS_EMITTED=NO")
print("MUTATION_PERFORMED=NO")
print("REPORT=" + str(OUT))
