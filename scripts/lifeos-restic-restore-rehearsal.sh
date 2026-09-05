#!/usr/bin/env bash
set -Eeuo pipefail
STATE_DIR="${HOME}/.local/state/lifeos/restore-rehearsal"
mkdir -p "$STATE_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo 'RESTORE_REHEARSAL=START'
svc=lifeos-restic-backup.service
systemctl show "$svc" -p LoadState --value >"$TMP/loadstate"
read -r loadstate <"$TMP/loadstate"
[[ "$loadstate" == loaded ]] || exit 2
systemctl cat "$svc" >"$TMP/unit"
python3 - "$TMP/unit" "$TMP/env" <<'PY'
import json
import re
import shlex
import sys
from pathlib import Path
unit = Path(sys.argv[1]).read_text(encoding='utf-8')
env = {}
for rawpath in re.findall(r'^\s*EnvironmentFile=-?([^\s]+)', unit, re.M):
    path = Path(rawpath.strip('"\''))
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        continue
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        for item in parts:
            allowed = re.match(
                r'^(RESTIC_|AWS_|B2_|AZURE_)[A-Z0-9_]+=', item
            )
            if allowed:
                key, value = item.split('=', 1)
                env[key] = value
if 'RESTIC_REPOSITORY' not in env:
    raise SystemExit('repository contract missing')
Path(sys.argv[2]).write_text(json.dumps(env), encoding='utf-8')
PY
python3 - "$TMP/env" "$TMP/latest.json" <<'PY'
import json
import os
import subprocess  # nosec B404
import sys
with open(sys.argv[1], encoding='utf-8') as handle:
    env_data = json.load(handle)
env = os.environ.copy()
env.update(env_data)
cmd = ['/usr/bin/restic', 'snapshots', '--latest', '1', '--json']
proc = subprocess.run(  # nosec B603
    cmd, env=env, text=True, check=True, stdout=subprocess.PIPE
)
with open(sys.argv[2], 'w', encoding='utf-8') as handle:
    handle.write(proc.stdout)
PY
python3 - "$TMP/latest.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding='utf-8') as handle:
    snapshots = json.load(handle)
assert snapshots
snapshot = snapshots[0]
print('SNAPSHOT_PRESENT=YES')
print('SNAPSHOT_TIME=' + str(snapshot.get('time', '')))
print('SNAPSHOT_HOST=' + str(snapshot.get('hostname', '')))
print('SNAPSHOT_PATH_COUNT=' + str(len(snapshot.get('paths') or [])))
PY
python3 - "$TMP/env" "$TMP/restore" <<'PY'
import json
import os
import subprocess  # nosec B404
import sys
with open(sys.argv[1], encoding='utf-8') as handle:
    env_data = json.load(handle)
env = os.environ.copy()
env.update(env_data)
subprocess.run(  # nosec B603
    ['/usr/bin/restic', 'check', '--read-data-subset=1/100'],
    env=env,
    check=True,
    stdout=subprocess.DEVNULL,
)
print('RESTIC_CHECK=PASS')
subprocess.run(  # nosec B603
    ['/usr/bin/restic', 'restore', 'latest', '--target', sys.argv[2]],
    env=env,
    check=True,
    stdout=subprocess.DEVNULL,
)
PY
python3 - "$TMP/restore" "$STATE_DIR" <<'PY'
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
root = Path(sys.argv[1])
state_dir = Path(sys.argv[2])
count = sum(1 for path in root.rglob('*') if path.is_file())
assert count > 0
print(f'RESTORED_FILE_COUNT={count}')
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
fd, tmp = tempfile.mkstemp(
    prefix='.restore-rehearsal-',
    dir=state_dir,
)
os.close(fd)
encoded = json.dumps(record, indent=2) + '\n'
Path(tmp).write_text(encoded, encoding='utf-8')
os.replace(tmp, state_dir / 'latest.json')
PY
echo 'PRODUCTION_OVERWRITE=NO'
echo 'SECRETS_EMITTED=NO'
echo 'RESTORE_REHEARSAL=PASS'
