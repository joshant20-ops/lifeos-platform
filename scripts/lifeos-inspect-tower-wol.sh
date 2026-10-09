#!/usr/bin/env bash
set -Eeuo pipefail
cd /home/joshan/lifeos-platform
python3 scripts/lifeos-tower-wol-packet-diagnostic.py --mode inspect --expected-fingerprint "" --run-id ""

echo '==> READ-ONLY LIVE HOME ASSISTANT WAKE PATH'
docker inspect --format 'HA_CONTAINER_STATUS={{.State.Status}} HA_NETWORK_MODE={{.HostConfig.NetworkMode}} HA_IMAGE={{.Config.Image}}' homeassistant
docker exec -i homeassistant python3 - <<'PY'
import hashlib, json, re, shutil, subprocess
from pathlib import Path

config = Path('/config/configuration.yaml')
raw = config.read_text() if config.is_file() else ''
match = re.search(r'(?ms)^command_line:\\s*\\n(.*?)(?=^[A-Za-z0-9_]+:|\\Z)', raw)
block = match.group(1) if match else ''
z97 = re.search(r'(?ms)^\\s*- switch:\\s*\\n(?:(?!^\\s*- switch:).)*?^\\s*name:\\s*Z97 Power\\s*\\n(?:(?!^\\s*- switch:).)*', block)
entry = z97.group(0) if z97 else ''
uid = re.search(r'(?m)^\\s*unique_id:\\s*([^\\s]+)', entry)
wake = re.search(r'/usr/local/bin/wakeonlan\\s+([0-9a-fA-F:.-]+)', entry)
lock = re.search(r'LOCK=([^;\\s]+)', entry)
print('HA_WAKE_INTEGRATION=' + ('command_line.switch' if entry else 'not-found'))
print('HA_WAKE_NAME=' + ('Z97 Power' if entry else 'not-found'))
print('HA_WAKE_UNIQUE_ID=' + (uid.group(1) if uid else 'not-found'))
print('HA_WAKE_EXECUTABLE=/usr/local/bin/wakeonlan')
print('HA_WAKE_MAC=' + (wake.group(1) if wake else 'not-found'))
print('HA_WAKE_LOCK_FILE=' + (lock.group(1) if lock else 'not-found'))
registry = Path('/config/.storage/core.entity_registry')
entity = 'not-found'
if registry.is_file():
    try:
        rows=json.loads(registry.read_text()).get('data',{}).get('entities',[])
        found=[e for e in rows if e.get('unique_id') == 'z97_power']
        if found:
            entity=str(found[0].get('entity_id') or 'unassigned')
            print('HA_WAKE_ENTITY_PLATFORM=' + str(found[0].get('platform') or 'unknown'))
    except Exception as exc:
        print('HA_ENTITY_REGISTRY_ERROR=' + type(exc).__name__)
print('HA_WAKE_ENTITY_ID=' + entity)

exe = Path('/usr/local/bin/wakeonlan')
print('HA_WAKE_EXECUTABLE_PRESENT=' + ('YES' if exe.is_file() else 'NO'))
if exe.is_file():
    print('HA_WAKE_EXECUTABLE_SHA256=' + hashlib.sha256(exe.read_bytes()).hexdigest())
    result=subprocess.run([str(exe), '--help'], text=True, capture_output=True, timeout=3, check=False)
    for line in (result.stdout + result.stderr).splitlines():
        if re.search(r'usage|default|broadcast|port|destination', line, re.I):
            print('HA_WAKE_HELP=' + ' '.join(line.split())[:220])

for root in (Path('/config/.storage'), Path('/config')):
    if not root.exists():
        continue
    files = root.glob('lovelace*') if root.name == '.storage' else [root/'scripts.yaml', root/'automations.yaml']
    for path in files:
        if not path.is_file():
            continue
        try:
            text=path.read_text(errors='replace')
        except OSError:
            continue
        if entity != 'not-found' and entity in text:
            for service in re.findall(r'(?m)^\\s*(?:service|action):\\s*([^\\s]+)', text):
                print(f'HA_WAKE_UI_OR_AUTOMATION_ACTION_FILE={path.name} ACTION={service}')
            if not re.search(r'(?m)^\\s*(?:service|action):\\s*', text):
                print(f'HA_WAKE_UI_OR_AUTOMATION_REFERENCE_FILE={path.name}')
PY
echo 'LIVE_HA_WAKE_INSPECTION=COMPLETE'
