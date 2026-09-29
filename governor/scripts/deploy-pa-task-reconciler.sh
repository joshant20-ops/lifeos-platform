#!/usr/bin/env bash
set -Eeuo pipefail
REPO=/home/joshan/lifeos-platform
SRC="$REPO/homelab/live/home/joshan/automation/lifeos_task_reconciler.py"
[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED reason=must_run_on_pi5_Docker"; exit 20; }
python3 -m py_compile "$SRC"
install -o root -g root -m 0755 "$SRC" /home/joshan/automation/lifeos_task_reconciler.py
install -o root -g root -m 0644 "$REPO/homelab/live/home/joshan/automation/lifeos_email_paperless_selective.py" /home/joshan/automation/lifeos_email_paperless_selective.py
cat >/etc/systemd/system/lifeos-task-reconciler.service <<'UNIT'
[Unit]
Description=LifeOS personal task reconciliation from Gmail and Paperless
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
User=root
Environment=HOME=/home/joshan
WorkingDirectory=/home/joshan/automation
LoadCredential=gmail-imap-user:/etc/lifeos/secrets/gmail-imap-user
LoadCredential=gmail-imap-password:/etc/lifeos/secrets/gmail-imap-password
LoadCredential=paperless_token:/etc/lifeos/secrets/paperless-api-token
ExecStart=/usr/bin/python3 /home/joshan/automation/lifeos_task_reconciler.py
TimeoutStartSec=30min
Nice=10
UNIT
cat >/etc/systemd/system/lifeos-task-reconciler.timer <<'UNIT'
[Unit]
Description=Refresh LifeOS personal tasks
[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
RandomizedDelaySec=10min
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now lifeos-task-reconciler.timer >/dev/null
systemctl start lifeos-task-reconciler.service
systemctl is-active --quiet lifeos-task-reconciler.timer
systemctl is-failed --quiet lifeos-task-reconciler.service && { journalctl -u lifeos-task-reconciler.service -n 60 --no-pager; exit 1; } || true
python3 - <<'PY'
import json,pathlib,time
p=pathlib.Path('/opt/stacks/homeassistant/config/www/lifeos_tasks.json')
j=json.loads(p.read_text())
assert j.get('schema')=='lifeos_tasks_v3'
assert isinstance(j.get('tasks'),list) and isinstance(j.get('resolved'),list)
assert time.time()-float(j.get('generated_time',0)) < 3600
print('TASK_RECONCILER=PASS')
print('OPEN_TASKS='+str(len(j['tasks'])))
print('RESOLVED_TASKS='+str(len(j['resolved'])))
print('MESSAGES_CONSIDERED='+str(j.get('messages_considered')))
print('ERRORS='+str(j.get('errors')))
PY
