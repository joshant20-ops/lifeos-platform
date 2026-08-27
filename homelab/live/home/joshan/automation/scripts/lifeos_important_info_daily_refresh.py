#!/usr/bin/env python3
from pathlib import Path
import subprocess, json, time, traceback

AUTO = Path('/home/joshan/automation')
LOGS = AUTO / 'logs'
LOGS.mkdir(parents=True, exist_ok=True)

steps = [
    ('paperless_rest_refresh', Path('/home/joshan/automation/scripts/lifeos_paperless_rest_refresh.py')),
    ('evidence_link_proposals', AUTO / 'scripts' / 'lifeos_evidence_link_proposals_refresh.py'),
    ('important_info_proposals', AUTO / 'scripts' / 'lifeos_important_info_proposals_refresh.py'),
    ('important_info_verification', AUTO / 'scripts' / 'lifeos_important_info_verification_refresh.py'),
    ('important_info_human_render', AUTO / 'scripts' / 'lifeos_important_info_human_render_refresh.py'),
]

result = {
    'ok': True,
    'generated_time': int(time.time()),
    'generated_iso': time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime()),
    'refresh_type': 'important_info_daily',
    'steps': []
}

for name, script in steps:
    step = {'name': name, 'script': str(script), 'ok': False}
    try:
        proc = subprocess.run(['python3', str(script)], capture_output=True, text=True, timeout=90)
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

out = LOGS / 'important_info_daily_refresh_status.json'
out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')

print(json.dumps(result, indent=2, sort_keys=True))
raise SystemExit(0 if result['ok'] else 1)
