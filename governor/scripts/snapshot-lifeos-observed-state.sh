#!/usr/bin/env bash
set -euo pipefail

SNAPSHOT_REPO=${LIFEOS_SNAPSHOTS_REPO:-/home/joshan/lifeos-snapshots}
PLATFORM_REPO=${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}
HOST_ROLE=${LIFEOS_HOST_ROLE:-pi5-controller}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
HOST=$(hostname)
OUT_DIR="$SNAPSHOT_REPO/snapshots/$HOST"
OUT="$OUT_DIR/$STAMP.json"
LATEST="$OUT_DIR/latest.json"

[[ -d "$SNAPSHOT_REPO/.git" ]] || {
  echo "RESULT=BLOCKED"
  echo "REASON=lifeos_snapshots_repo_missing path=$SNAPSHOT_REPO"
  exit 30
}

mkdir -p "$OUT_DIR"

python3 - "$OUT" "$HOST" "$HOST_ROLE" "$PLATFORM_REPO" <<'PY'
import hashlib
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

out = pathlib.Path(sys.argv[1])
host = sys.argv[2]
role = sys.argv[3]
repo = pathlib.Path(sys.argv[4])


def run(args):
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=20).stdout.strip()
    except Exception:
        return ''


def sha(path):
    p = pathlib.Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

services = {}
for name in (
    'lifeos-autonomous-agent.service',
    'lifeos-engineer.service',
    'lifeos-assistant.service',
    'docker.service',
):
    services[name] = run(['systemctl', 'is-active', name]) or 'unknown'

containers = []
raw = run(['docker', 'ps', '--format', '{{.Names}}|{{.Image}}|{{.Status}}'])
for line in raw.splitlines():
    parts = line.split('|', 2)
    if len(parts) == 3:
        containers.append({'name': parts[0], 'image': parts[1], 'status': parts[2]})

head = run(['git', '-C', str(repo), 'rev-parse', 'HEAD']) if (repo / '.git').exists() else None
origin = run(['git', '-C', str(repo), 'rev-parse', 'origin/main']) if (repo / '.git').exists() else None

payload = {
    'schema_version': 1,
    'captured_at': datetime.now(timezone.utc).isoformat(),
    'host': host,
    'host_role': role,
    'desired_state_repo': {
        'path': str(repo),
        'head': head or None,
        'origin_main': origin or None,
    },
    'services': services,
    'control_plane_hashes': {
        '/usr/local/libexec/lifeos-autonomous-agent': sha('/usr/local/libexec/lifeos-autonomous-agent'),
        '/usr/local/libexec/lifeos-engineer': sha('/usr/local/libexec/lifeos-engineer'),
    },
    'containers': containers,
}

# Intentionally no environment values, logs, secrets, HA history, document content,
# network credentials, tokens, or arbitrary config file contents.
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n')
PY

cp "$OUT" "$LATEST"

cd "$SNAPSHOT_REPO"
git add "snapshots/$HOST"
if git diff --cached --quiet; then
  echo "RESULT=PASS"
  echo "SNAPSHOT=no_change"
  exit 0
fi

git diff --cached --check
git commit -m "snapshot: $HOST $STAMP" >/dev/null
git push origin HEAD:main >/dev/null

echo "RESULT=PASS"
echo "SNAPSHOT=$OUT"
echo "AUTHORITY=evidence_only"
