#!/usr/bin/env python3
from pathlib import Path
import subprocess, json, time, traceback

AUTO = Path('/home/joshan/automation')
LOGS = AUTO / 'logs'
LOGS.mkdir(parents=True, exist_ok=True)

steps = [
    ('ha_dashboard_export', AUTO / 'scripts' / 'lifeos_pa_ha_dashboard_export.py'),
    ('escalation_engine', AUTO / 'scripts' / 'lifeos_pa_escalation_engine.py'),
]

result = {
    'ok': True,
    'generated_time': int(time.time()),
    'generated_iso': time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime()),
    'refresh_type': 'pa_lifecycle_5min',
    'steps': []
}

for name, script in steps:
    step = {'name': name, 'script': str(script), 'ok': False}
    try:
        proc = subprocess.run(['python3', str(script)], capture_output=True, text=True, timeout=60)
        step['returncode'] = proc.returncode
        step['stdout_tail'] = proc.stdout[-2000:]
        step['stderr_tail'] = proc.stderr[-2000:]
        step['ok'] = proc.returncode == 0
        if proc.returncode != 0:
            result['ok'] = False
    except Exception as e:
        step['error'] = str(e)
        step['traceback'] = traceback.format_exc()
        result['ok'] = False
    result['steps'].append(step)

out = LOGS / 'pa_dashboard_refresh_status.json'
out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')

print(json.dumps(result, indent=2, sort_keys=True))
raise SystemExit(0 if result['ok'] else 1)
