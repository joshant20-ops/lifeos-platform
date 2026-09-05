#!/usr/bin/env bash
set -Eeuo pipefail
python3 - <<'PY'
import json
import os
import re
import shlex
import subprocess  # nosec
import tempfile
from datetime import datetime, timezone
from pathlib import Path

print('RESTORE_REHEARSAL=START')
svc = 'lifeos-restic-backup.service'
systemctl = '/usr/bin/systemctl'


def systemctl_text(*args):
    proc = subprocess.run(
        [systemctl, *args],
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    return proc.stdout


state = systemctl_text('show', svc, '-p', 'LoadState', '--value').strip()
if state != 'loaded':
    raise SystemExit('backup service missing')
pattern = (
    r'^(RESTIC_[A-Z0-9_]+|AWS_[A-Z0-9_]+|'
    r'B2_[A-Z0-9_]+|AZURE_[A-Z0-9_]+)='
)
allow = re.compile(pattern)
env_text = systemctl_text('show', svc, '-p', 'Environment', '--value')
items = shlex.split(env_text)
unit = systemctl_text('cat', svc)
for rawpath in re.findall(r'^\s*EnvironmentFile=-?([^\s]+)', unit, re.M):
    path = Path(rawpath.strip('"\''))
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        continue
    for rawline in lines:
        line = rawline.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        try:
            items.extend(shlex.split(line, comments=True, posix=True))
        except ValueError:
            continue
env = os.environ.copy()
for item in items:
    if allow.match(item):
        key, value = item.split('=', 1)
        env[key] = value
if 'RESTIC_REPOSITORY' not in env:
    raise SystemExit('repository contract missing')


def restic(*args, capture=False):
    stdout = subprocess.PIPE if capture else subprocess.DEVNULL
    return subprocess.run(
        ['/usr/bin/restic', *args],
        env=env,
        text=True,
        check=True,
        stdout=stdout,
    )


snap_run = restic('snapshots', '--latest', '1', '--json', capture=True)
snaps = json.loads(snap_run.stdout)
if not snaps:
    raise SystemExit('no snapshots')
snapshot = snaps[0]
print('SNAPSHOT_PRESENT=YES')
print('SNAPSHOT_TIME=' + str(snapshot.get('time', '')))
print('SNAPSHOT_HOST=' + str(snapshot.get('hostname', '')))
print('SNAPSHOT_PATH_COUNT=' + str(len(snapshot.get('paths') or [])))
restic('check', '--read-data-subset=1/100')
print('RESTIC_CHECK=PASS')
with tempfile.TemporaryDirectory() as td:
    target = Path(td) / 'restore'
    restic('restore', 'latest', '--target', str(target))
    count = 0
    for file_path in target.rglob('*'):
        if file_path.is_file():
            count += 1
    if count <= 0:
        raise SystemExit('no files restored')
    print(f'RESTORED_FILE_COUNT={count}')
state_dir = Path.home() / '.local' / 'state' / 'lifeos'
state_dir = state_dir / 'restore-rehearsal'
state_dir.mkdir(parents=True, exist_ok=True)
record = {
    'schema_version': 1,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'result': 'PASS',
    'repository_check': 'PASS',
    'actual_restore': 'PASS',
    'restored_file_count': count,
    'production_overwrite': False,
    'secrets_emitted': False,
}
fd, tmp = tempfile.mkstemp(prefix='.restore-rehearsal-', dir=state_dir)
os.close(fd)
encoded = json.dumps(record, indent=2, sort_keys=True) + '\n'
Path(tmp).write_text(encoded, encoding='utf-8')
os.replace(tmp, state_dir / 'latest.json')
print('PRODUCTION_OVERWRITE=NO')
print('SECRETS_EMITTED=NO')
print('RESTORE_REHEARSAL=PASS')
PY
