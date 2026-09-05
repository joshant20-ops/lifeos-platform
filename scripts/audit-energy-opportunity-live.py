#!/usr/bin/env python3
"""Read-only Phase 2B audit for Energy Opportunity Alerting."""
from __future__ import annotations
import json, os, subprocess, urllib.request
from pathlib import Path

OUT=Path.home()/'.local/state/lifeos/energy-opportunity-audit.json'

def run(cmd):
    return subprocess.run(cmd,text=True,capture_output=True)

def docker_exec(*args):
    return run(['docker','exec','homeassistant',*args])

def fail(msg):
    print('ENERGY_OPPORTUNITY_AUDIT=FAIL')
    print('DETAIL='+msg.replace('\n',' | ')[:2000])
    raise SystemExit(1)

# Existing LifeOS Energy runtime / Octopus credentials contract.
r=run(['docker','inspect','lifeos-energy'])
if r.returncode: fail('lifeos-energy container missing')
inspect=json.loads(r.stdout)[0]
env=inspect.get('Config',{}).get('Env',[])
mounts=inspect.get('Mounts',[])
oct_env=[x.split('=',1)[0] for x in env if x.startswith('OCTOPUS_')]
oct_mounts=[m.get('Destination') for m in mounts if 'octopus' in (m.get('Destination','')+m.get('Source','')).lower() or 'lifeos-energy' in m.get('Destination','')]

# Home Assistant: inspect entity registry/state via local container files only; never print values/tokens.
registry=docker_exec('python3','-c',"import json;d=json.load(open('/config/.storage/core.entity_registry'));print('\\n'.join(x.get('entity_id','') for x in d.get('data',{}).get('entities',[])))")
entities=registry.stdout.splitlines() if registry.returncode==0 else []
octopus_entities=sorted(x for x in entities if 'octopus' in x.lower() or 'agile' in x.lower())
notify_entities=sorted(x for x in entities if x.startswith(('notify.','media_player.')) or 'alexa' in x.lower())

# HA config/source markers for Alexa/WhatsApp without exposing secrets.
scan=docker_exec('sh','-lc',"grep -RilE 'alexa|whatsapp|notify\\.' /config/*.yaml /config/packages /config/automations.yaml /config/scripts.yaml 2>/dev/null | head -100")
notification_files=sorted(set(scan.stdout.splitlines())) if scan.returncode in (0,1) else []

# Existing powerdown feed consumed by LifeOS Energy.
powerdown=Path('/opt/lifeos-watch/octopus-powerdown')
powerdown_files=[]
if powerdown.exists():
    for p in powerdown.rglob('*'):
        if p.is_file(): powerdown_files.append(str(p))

# Runtime health/status shape only.
health={}
for path in ('/health','/api/status'):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8110'+path,timeout=5) as resp:
            health[path]={'status':resp.status,'body':resp.read(4096).decode('utf-8','replace')}
    except Exception as e:
        health[path]={'error':type(e).__name__}

report={
 'schema_version':1,
 'phase':'2B',
 'lifeos_energy_running':inspect.get('State',{}).get('Running',False),
 'lifeos_energy_octopus_env_names':oct_env,
 'lifeos_energy_octopus_mounts':oct_mounts,
 'ha_octopus_entity_ids':octopus_entities,
 'ha_notification_entity_ids':notify_entities,
 'ha_notification_config_files':notification_files,
 'powerdown_feed_present':powerdown.exists(),
 'powerdown_feed_files':powerdown_files,
 'lifeos_energy_endpoints':health,
 'secrets_emitted':False,
}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print('ENERGY_OPPORTUNITY_AUDIT=PASS')
print('LIFEOS_ENERGY_RUNNING='+('YES' if report['lifeos_energy_running'] else 'NO'))
print('OCTOPUS_SECRET_CONTRACT='+('YES' if oct_env or oct_mounts else 'NO'))
print('HA_OCTOPUS_ENTITIES='+str(len(octopus_entities)))
print('HA_NOTIFICATION_ENTITIES='+str(len(notify_entities)))
print('HA_NOTIFICATION_CONFIG_FILES='+str(len(notification_files)))
print('POWERDOWN_FEED_PRESENT='+('YES' if powerdown.exists() else 'NO'))
print('POWERDOWN_FEED_FILES='+str(len(powerdown_files)))
print('SECRETS_EMITTED=NO')
print('REPORT='+str(OUT))
