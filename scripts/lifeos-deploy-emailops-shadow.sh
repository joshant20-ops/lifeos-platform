#!/usr/bin/env bash
set -Eeuo pipefail
REPO=/home/joshan/lifeos-platform
BUILD=/home/joshan/emailops-shadow-build
DEST=/opt/lifeos/emailops-shadow
PROFILE=/home/joshan/.local/share/lifeos/emailops-shadow
[[ "$(hostname)" == Docker && "$(uname -m)" == aarch64 ]] || { echo EMAILOPS_INSTALL=WRONG_RUNTIME; exit 20; }
[[ $EUID -eq 0 ]] || exit 20
if systemctl is-active --quiet lifeos-emailops-shadow.service; then echo EMAILOPS_INSTALL=ALREADY_RUNNING; exit 20; fi
for secret in gmail-imap-user gmail-imap-password; do
  [[ -f /etc/lifeos/secrets/$secret && ! -L /etc/lifeos/secrets/$secret ]] || { echo EMAILOPS_INSTALL=CREDENTIAL_MISSING; exit 20; }
done
python3 - <<'PY'
import hashlib, json, pathlib, subprocess
repo = pathlib.Path('/home/joshan/lifeos-platform')
build = pathlib.Path('/home/joshan/emailops-shadow-build')
pin = json.loads((repo / 'config/emailops-upstream.json').read_text())
manifest = json.loads((build / 'manifest.json').read_text())
assert manifest['schema'] == 'lifeos_emailops_build_v1'
assert manifest.get('debug_assertions') is False
assert manifest.get('credential_backend') == 'native_keyring'
assert manifest['platform_commit'] == subprocess.check_output(['runuser','-u','joshan','--','git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
assert manifest['source_commit'] == pin['commit']
assert manifest['source_archive_sha256'] == pin['archive_sha256']
assert manifest['patch_sha256'] == pin['patch_sha256']
binary = build / 'emailops-cli'
assert not binary.is_symlink()
assert hashlib.sha256(binary.read_bytes()).hexdigest() == manifest['binary_sha256']
assert binary.read_bytes()[:6] == b'\x7fELF\x02\x01'
assert binary.read_bytes()[18:20] == b'\xb7\x00', 'binary must be ARM64'
assert pin['mode'] == 'shadow' and pin['mailbox_writes'] is False
print('EMAILOPS_ARTIFACT_INTEGRITY=PASS')
PY
# Only the native Linux credential service is added to Pi5; compiler/model builds
# happen on the cloud-safe ARM builder. No desktop or new mailbox authority.
if ! command -v gnome-keyring-daemon >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gnome-keyring > /var/log/lifeos-emailops-dependencies.log 2>&1
fi
command -v dbus-run-session >/dev/null
command -v gnome-keyring-daemon >/dev/null
install -d -o root -g root -m 0755 "$DEST" "$DEST/bin" "$DEST/backups"
install -d -o joshan -g joshan -m 0700 "$PROFILE"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$DEST/backups/$STAMP"
install -d -o root -g root -m 0700 "$BACKUP"
for file in bin/emailops-cli manifest.json; do
  if [[ -f "$DEST/$file" ]]; then cp -a "$DEST/$file" "$BACKUP/$(basename "$file")"; fi
done
if [[ -f /etc/systemd/system/lifeos-emailops-shadow.service ]]; then
  cp -a /etc/systemd/system/lifeos-emailops-shadow.service "$BACKUP/service"
fi
install -o root -g root -m 0755 "$BUILD/emailops-cli" "$DEST/bin/emailops-cli.new"
mv "$DEST/bin/emailops-cli.new" "$DEST/bin/emailops-cli"
install -o root -g root -m 0644 "$BUILD/manifest.json" "$DEST/manifest.json"
if [[ ! -e /etc/lifeos/secrets/emailops-keyring-password ]]; then
  python3 - <<'PY'
import os, secrets
fd = os.open('/etc/lifeos/secrets/emailops-keyring-password', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream: stream.write(secrets.token_hex(32) + '\n')
PY
fi
cat > /etc/systemd/system/lifeos-emailops-shadow.service <<'UNIT'
[Unit]
Description=LifeOS EmailOps isolated read-only shadow evaluation
After=network-online.target
[Service]
Type=oneshot
User=joshan
Group=joshan
WorkingDirectory=/home/joshan/lifeos-platform
Environment=HOME=/home/joshan
Environment=XDG_RUNTIME_DIR=/run/lifeos-emailops-shadow
RuntimeDirectory=lifeos-emailops-shadow
RuntimeDirectoryMode=0700
LoadCredential=gmail-imap-user:/etc/lifeos/secrets/gmail-imap-user
LoadCredential=gmail-imap-password:/etc/lifeos/secrets/gmail-imap-password
LoadCredential=emailops-keyring-password:/etc/lifeos/secrets/emailops-keyring-password
ExecStart=/usr/bin/dbus-run-session -- /usr/bin/python3 /home/joshan/lifeos-platform/governor/emailops_shadow_runtime.py
TimeoutStartSec=20min
UMask=0077
Nice=15
CPUQuota=50%
MemoryMax=1536M
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/joshan/.local/share/lifeos/emailops-shadow
UNIT
# Install the same isolated boundary for the future confirmed Junk action. It
# cannot run successfully until the source policy records live/user acceptance.
sed 's/isolated read-only shadow evaluation/verified user-confirmed Junk/; s@governor/emailops_shadow_runtime.py$@governor/emailops_shadow_runtime.py --confirm-junk@' \
  /etc/systemd/system/lifeos-emailops-shadow.service > /etc/systemd/system/lifeos-emailops-junk.service
systemctl daemon-reload
if ! systemctl start lifeos-emailops-shadow.service; then
  journalctl -u lifeos-emailops-shadow.service -n 35 --no-pager -o cat | grep -E '^EMAILOPS_[A-Z_]+=[a-zA-Z0-9_]+$' || true
  if [[ -f "$BACKUP/emailops-cli" ]]; then cp -a "$BACKUP/emailops-cli" "$DEST/bin/emailops-cli"; fi
  if [[ -f "$BACKUP/manifest.json" ]]; then cp -a "$BACKUP/manifest.json" "$DEST/manifest.json"; fi
  if [[ -f "$BACKUP/service" ]]; then cp -a "$BACKUP/service" /etc/systemd/system/lifeos-emailops-shadow.service; fi
  systemctl daemon-reload
  echo EMAILOPS_INSTALL=FAILED_PROFILE_PRESERVED
  exit 1
fi
journalctl -u lifeos-emailops-shadow.service -n 35 --no-pager -o cat | grep -E '^EMAILOPS_[A-Z_]+=[a-zA-Z0-9_]+$'
python3 - <<'PY'
import json, pathlib, re, sys
sys.path.insert(0, '/home/joshan/lifeos-platform')
from governor.emailops_adapter import write_private_json
profile = pathlib.Path('/home/joshan/.local/share/lifeos/emailops-shadow')
report = json.loads((profile / 'shadow-report.json').read_text())
destination = pathlib.Path('/opt/stacks/homeassistant/config/lifeos-pa-state/emailops-shadow')
for result in report['results']:
    for task_id in result['matched_task_ids']:
        assert re.fullmatch(r'[a-z0-9][a-z0-9-]{0,119}', task_id)
        write_private_json(destination / (task_id + '.json'), {
            'schema': 'lifeos_emailops_shadow_task_v1', 'task_id': task_id,
            'generated_at': report['generated_at'], 'summary': result.get('summary'),
            'proposals': result['proposals'],
        })
print('EMAILOPS_PRIVATE_REVIEW=READY')
PY
echo EMAILOPS_INSTALL=PASS
