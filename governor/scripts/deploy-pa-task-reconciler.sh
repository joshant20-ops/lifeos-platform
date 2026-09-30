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

HA_CONFIG=/opt/stacks/homeassistant/config
HA_PACKAGE="$HA_CONFIG/packages/lifeos_attention.yaml"
HA_SENSOR="$HA_CONFIG/scripts/lifeos_pa_task_attention_sensor.py"
HA_USER_MODULE="$HA_CONFIG/scripts/lifeos_pa_user_state.py"
HA_ACTION="$HA_CONFIG/scripts/lifeos_pa_user_action.py"
HA_ACTIONS="$HA_CONFIG/packages/lifeos_actions.yaml"
PA_STATE_DIR="$HA_CONFIG/lifeos-pa-state"
PA_USER_STATE="$PA_STATE_DIR/user_state.json"
BACKUP_DIR=/home/joshan/automation/backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"
HA_CHANGED=0
if ! cmp -s "$REPO/homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml" "$HA_PACKAGE"; then
  cp -a "$HA_PACKAGE" "$BACKUP_DIR/lifeos_attention.yaml.pre-pa-attention.$STAMP"
  install -o root -g root -m 0644 "$REPO/homelab/live/opt/stacks/homeassistant/config/packages/lifeos_attention.yaml" "$HA_PACKAGE"
  HA_CHANGED=1
fi
if ! cmp -s "$REPO/homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py" "$HA_SENSOR"; then
  install -d -o root -g root -m 0755 "$HA_CONFIG/scripts"
  install -o root -g root -m 0755 "$REPO/homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_task_attention_sensor.py" "$HA_SENSOR"
  HA_CHANGED=1
fi
if ! cmp -s "$REPO/governor/pa_user_state.py" "$HA_USER_MODULE"; then
  install -o root -g root -m 0644 "$REPO/governor/pa_user_state.py" "$HA_USER_MODULE"
  HA_CHANGED=1
fi
if ! cmp -s "$REPO/homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_user_action.py" "$HA_ACTION"; then
  install -o root -g root -m 0755 "$REPO/homelab/live/opt/stacks/homeassistant/config/scripts/lifeos_pa_user_action.py" "$HA_ACTION"
  HA_CHANGED=1
fi
if ! cmp -s "$REPO/homelab/live/opt/stacks/homeassistant/config/packages/lifeos_actions.yaml" "$HA_ACTIONS"; then
  cp -a "$HA_ACTIONS" "$BACKUP_DIR/lifeos_actions.yaml.pre-pa-user-actions.$STAMP"
  install -o root -g root -m 0644 "$REPO/homelab/live/opt/stacks/homeassistant/config/packages/lifeos_actions.yaml" "$HA_ACTIONS"
  HA_CHANGED=1
fi
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR"
if [[ ! -e "$PA_USER_STATE" ]]; then
  install -o joshan -g joshan -m 0600 /dev/null "$PA_USER_STATE"
  sudo -u joshan sh -c 'printf "%s\n" "{\"schema\":\"lifeos_pa_user_state_v1\",\"revision\":0,\"obligations\":{}}" > "$1"' sh "$PA_USER_STATE"
fi
chown joshan:joshan "$PA_USER_STATE"
chmod 0600 "$PA_USER_STATE"
if ! python3 "$REPO/homeassistant/deploy-lifeos-dashboard.py" --check >/dev/null 2>&1; then
  python3 "$REPO/homeassistant/deploy-lifeos-dashboard.py"
  HA_CHANGED=1
fi
if [ "$HA_CHANGED" -eq 1 ]; then
  if ! docker exec homeassistant python -m homeassistant --script check_config --config /config; then
    if [ -f "$BACKUP_DIR/lifeos_attention.yaml.pre-pa-attention.$STAMP" ]; then
      cp -a "$BACKUP_DIR/lifeos_attention.yaml.pre-pa-attention.$STAMP" "$HA_PACKAGE"
    fi
    if [ -f "$BACKUP_DIR/lifeos_actions.yaml.pre-pa-user-actions.$STAMP" ]; then
      cp -a "$BACKUP_DIR/lifeos_actions.yaml.pre-pa-user-actions.$STAMP" "$HA_ACTIONS"
    fi
    echo 'HA_CONFIG_VALIDATION=FAIL'
    exit 1
  fi
  echo 'HA_CONFIG_VALIDATION=PASS'
  docker restart homeassistant >/dev/null
  ready=0
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 3 http://127.0.0.1:8123/ >/dev/null; then ready=1; break; fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    if [ -f "$BACKUP_DIR/lifeos_attention.yaml.pre-pa-attention.$STAMP" ]; then
      cp -a "$BACKUP_DIR/lifeos_attention.yaml.pre-pa-attention.$STAMP" "$HA_PACKAGE"
      docker restart homeassistant >/dev/null || true
    fi
    echo 'HA_CORE_RESTART=FAIL'
    exit 1
  fi
  echo 'HA_CORE_RESTART=PASS'
else
  echo 'HA_CONFIG_CHANGE=NONE'
fi
docker exec homeassistant python3 /config/scripts/lifeos_pa_task_attention_sensor.py | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("state") in {"attention","clear"}; print("PA_ATTENTION_SENSOR=PASS"); print("NEEDS_ME="+str(d.get("needs_me",0))); print("WAITING="+str(d.get("waiting_on_others",0))); print("DUE_OR_OVERDUE="+str(int(d.get("overdue",0))+int(d.get("upcoming",0))))'
