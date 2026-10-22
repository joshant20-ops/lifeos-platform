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
cat >/etc/systemd/system/lifeos-task-reconciler.path <<'UNIT'
[Unit]
Description=Process user-confirmed LifeOS Junk and task review requests promptly
[Path]
PathExistsGlob=/opt/stacks/homeassistant/config/lifeos-pa-state/junk-requests/*.json
PathExistsGlob=/opt/stacks/homeassistant/config/lifeos-pa-state/review-requests/*.json
Unit=lifeos-task-reconciler.service
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now lifeos-task-reconciler.timer >/dev/null
install -d -o joshan -g joshan -m 0700 /opt/stacks/homeassistant/config/lifeos-pa-state/junk-requests
install -d -o joshan -g joshan -m 0700 /opt/stacks/homeassistant/config/lifeos-pa-state/junk-requests/failed
install -d -o joshan -g joshan -m 0700 /opt/stacks/homeassistant/config/lifeos-pa-state/review-requests
install -d -o joshan -g joshan -m 0700 /opt/stacks/homeassistant/config/lifeos-pa-state/review-requests/failed
install -d -o joshan -g joshan -m 0700 /opt/stacks/homeassistant/config/lifeos-pa-state/task-reviews
systemctl enable --now lifeos-task-reconciler.path >/dev/null
paperless_runtime_diagnostic() {
  /usr/bin/python3 "$REPO/governor/paperless_runtime_diagnostic.py"
}

if ! systemctl start lifeos-task-reconciler.service; then
  echo 'TASK_RECONCILER_SERVICE=FAIL'
  journalctl -u lifeos-task-reconciler.service -n 80 --no-pager -o cat |
    grep -E '^TASK_RECONCILER_FAILURE_(STAGE|BUCKET)=[A-Za-z0-9_]+$' |
    tail -n 2 || true
  paperless_runtime_diagnostic
  exit 1
fi
systemctl is-active --quiet lifeos-task-reconciler.timer
systemctl is-active --quiet lifeos-task-reconciler.path
if systemctl is-failed --quiet lifeos-task-reconciler.service; then
  echo 'TASK_RECONCILER_SERVICE=FAIL'
  journalctl -u lifeos-task-reconciler.service -n 80 --no-pager -o cat |
    grep -E '^TASK_RECONCILER_FAILURE_(STAGE|BUCKET)=[A-Za-z0-9_]+$' |
    tail -n 2 || true
  paperless_runtime_diagnostic
  exit 1
fi
python3 - <<'PY'
import json,pathlib,time
p=pathlib.Path('/opt/stacks/homeassistant/config/www/lifeos_tasks.json')
j=json.loads(p.read_text())
assert j.get('schema')=='lifeos_tasks_v3'
assert isinstance(j.get('tasks'),list) and isinstance(j.get('resolved'),list)
assert time.time()-float(j.get('generated_time',0)) < 3600
print('TASK_RECONCILER=PASS' if int(j.get('errors',0))==0 else 'TASK_RECONCILER=FAIL')
print('OPEN_TASKS='+str(len(j['tasks'])))
print('RESOLVED_TASKS='+str(len(j['resolved'])))
print('MESSAGES_CONSIDERED='+str(j.get('messages_considered')))
print('ERRORS='+str(j.get('errors')))
PY

HA_CONFIG=/opt/stacks/homeassistant/config

# Forward only fixed counters and safe categories; never emit private source/model data.
journalctl -u lifeos-task-reconciler.service -n 20 --no-pager -o cat |
  grep -E '^TASK_(FETCH|CLASSIFICATION)_ERRORS=[0-9]+$|^TASK_CLASSIFICATION_ERROR_CATEGORIES=[A-Z0-9_,=]+$' |
  tail -n 3 || true
journalctl -u lifeos-task-reconciler.service -n 20 --no-pager -o cat |
  grep -E '^TASK_(STALE_SOURCE_EMAILS_FETCHED|NO_ACTION_SOURCE_EMAILS|NO_ACTION_TASKS_REMOVED|STALE_SOURCE_EMAILS_FETCH_FAILED)=[0-9]+ |
  tail -n 3 || true

ERROR_COUNT=$(python3 - <<'PY'
import json,pathlib
j=json.loads(pathlib.Path('/opt/stacks/homeassistant/config/www/lifeos_tasks.json').read_text())
print(int(j.get('errors',0)))
PY
)
if [[ ! "$ERROR_COUNT" =~ ^[0-9]+$ ]]; then
  echo 'TASK_RECONCILER_ERROR_GATE=INVALID'
  exit 1
fi
if (( ERROR_COUNT != 0 )); then
  echo 'TASK_RECONCILER_ERROR_GATE=FAIL'
  exit 1
fi
echo 'TASK_RECONCILER_ERROR_GATE=PASS'

HA_PACKAGE="$HA_CONFIG/packages/lifeos_attention.yaml"
HA_SENSOR="$HA_CONFIG/scripts/lifeos_pa_task_attention_sensor.py"
HA_USER_MODULE="$HA_CONFIG/scripts/lifeos_pa_user_state.py"
HA_ACTION="$HA_CONFIG/scripts/lifeos_pa_user_action.py"
HA_ACTIONS="$HA_CONFIG/packages/lifeos_actions.yaml"
PA_STATE_DIR="$HA_CONFIG/lifeos-pa-state"
PA_USER_STATE="$PA_STATE_DIR/user_state.json"
HA_REVIEW_COMPONENT="$HA_CONFIG/custom_components/lifeos_pa_review"
BACKUP_DIR=/home/joshan/automation/backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"
HA_CHANGED=0
REVIEW_COMPONENT_CHANGED=0
REVIEW_COMPONENT_BACKUP="$BACKUP_DIR/lifeos_pa_review.pre.$STAMP"
rollback_review_component() {
  for file in __init__.py manifest.json; do
    if [ -f "$REVIEW_COMPONENT_BACKUP/$file" ]; then
      install -o root -g root -m 0644 "$REVIEW_COMPONENT_BACKUP/$file" "$HA_REVIEW_COMPONENT/$file"
    elif [ -f "$REVIEW_COMPONENT_BACKUP/.new-$file" ]; then
      rm -f "$HA_REVIEW_COMPONENT/$file"
    fi
  done
  rmdir "$HA_REVIEW_COMPONENT" 2>/dev/null || true
}
install -d -o root -g root -m 0755 "$HA_CONFIG/custom_components" "$HA_REVIEW_COMPONENT"
for file in __init__.py manifest.json; do
  source_file="$REPO/homelab/live/opt/stacks/homeassistant/config/custom_components/lifeos_pa_review/$file"
  target_file="$HA_REVIEW_COMPONENT/$file"
  if ! cmp -s "$source_file" "$target_file"; then
    install -d -o root -g root -m 0755 "$REVIEW_COMPONENT_BACKUP"
    if [ -f "$target_file" ]; then
      cp -a "$target_file" "$REVIEW_COMPONENT_BACKUP/$file"
    else
      touch "$REVIEW_COMPONENT_BACKUP/.new-$file"
    fi
    install -o root -g root -m 0644 "$source_file" "$target_file"
    HA_CHANGED=1
    REVIEW_COMPONENT_CHANGED=1
  fi
done
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
JUNK_QUEUE_DIR="$PA_STATE_DIR/junk-requests"
install -d -o joshan -g joshan -m 0700 "$JUNK_QUEUE_DIR"
install -d -o joshan -g joshan -m 0700 "$JUNK_QUEUE_DIR/failed"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/review-requests"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/review-requests/failed"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/task-reviews"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/task-previews"
systemctl is-active --quiet lifeos-task-reconciler.path
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
    if [ "$REVIEW_COMPONENT_CHANGED" -eq 1 ]; then rollback_review_component; fi
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
    if [ "$REVIEW_COMPONENT_CHANGED" -eq 1 ]; then
      rollback_review_component
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
python3 - <<'PYPROBE'
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

task_id = "runtime-auth-" + uuid.uuid4().hex
marker = "LIFEOS_PRIVATE_PREVIEW_AUTH_PROBE_" + uuid.uuid4().hex
preview_path = Path("/config/lifeos-pa-state/task-previews") / (task_id + ".json")
preview_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
preview_path.write_text(json.dumps({
    "schema": "lifeos_pa_task_previews_v1",
    "task_id": task_id,
    "generated_at": int(time.time()),
    "documents": [{"document_id": "1", "title": "synthetic probe", "ocr_text": marker}],
}), encoding="utf-8")
os.chmod(preview_path, 0o600)
try:
    request = urllib.request.Request(
        "http://127.0.0.1:8123/api/lifeos_pa_review/" + task_id,
        headers={"".join(("Author", "ization")): "Bearer invalid-lifeos-preview-probe"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = response.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read(20000).decode("utf-8", "replace")
    leaked = marker in body
    print("PA_REVIEW_PREVIEW_API_HTTP=" + str(status))
    print("PA_REVIEW_PREVIEW_API_MARKER_LEAK=" + ("YES" if leaked else "NO"))
    if status in {401, 403, 404} and not leaked:
        print("PA_REVIEW_PREVIEW_API_AUTH=PASS")
    else:
        print("PA_REVIEW_PREVIEW_API_AUTH=FAIL")
        raise SystemExit(1)
finally:
    preview_path.unlink(missing_ok=True)
PYPROBE
 |
  tail -n 3 || true

ERROR_COUNT=$(python3 - <<'PY'
import json,pathlib
j=json.loads(pathlib.Path('/opt/stacks/homeassistant/config/www/lifeos_tasks.json').read_text())
print(int(j.get('errors',0)))
PY
)
if [[ ! "$ERROR_COUNT" =~ ^[0-9]+$ ]]; then
  echo 'TASK_RECONCILER_ERROR_GATE=INVALID'
  exit 1
fi
if (( ERROR_COUNT != 0 )); then
  echo 'TASK_RECONCILER_ERROR_GATE=FAIL'
  exit 1
fi
echo 'TASK_RECONCILER_ERROR_GATE=PASS'

HA_PACKAGE="$HA_CONFIG/packages/lifeos_attention.yaml"
HA_SENSOR="$HA_CONFIG/scripts/lifeos_pa_task_attention_sensor.py"
HA_USER_MODULE="$HA_CONFIG/scripts/lifeos_pa_user_state.py"
HA_ACTION="$HA_CONFIG/scripts/lifeos_pa_user_action.py"
HA_ACTIONS="$HA_CONFIG/packages/lifeos_actions.yaml"
PA_STATE_DIR="$HA_CONFIG/lifeos-pa-state"
PA_USER_STATE="$PA_STATE_DIR/user_state.json"
HA_REVIEW_COMPONENT="$HA_CONFIG/custom_components/lifeos_pa_review"
BACKUP_DIR=/home/joshan/automation/backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"
HA_CHANGED=0
REVIEW_COMPONENT_CHANGED=0
REVIEW_COMPONENT_BACKUP="$BACKUP_DIR/lifeos_pa_review.pre.$STAMP"
rollback_review_component() {
  for file in __init__.py manifest.json; do
    if [ -f "$REVIEW_COMPONENT_BACKUP/$file" ]; then
      install -o root -g root -m 0644 "$REVIEW_COMPONENT_BACKUP/$file" "$HA_REVIEW_COMPONENT/$file"
    elif [ -f "$REVIEW_COMPONENT_BACKUP/.new-$file" ]; then
      rm -f "$HA_REVIEW_COMPONENT/$file"
    fi
  done
  rmdir "$HA_REVIEW_COMPONENT" 2>/dev/null || true
}
install -d -o root -g root -m 0755 "$HA_CONFIG/custom_components" "$HA_REVIEW_COMPONENT"
for file in __init__.py manifest.json; do
  source_file="$REPO/homelab/live/opt/stacks/homeassistant/config/custom_components/lifeos_pa_review/$file"
  target_file="$HA_REVIEW_COMPONENT/$file"
  if ! cmp -s "$source_file" "$target_file"; then
    install -d -o root -g root -m 0755 "$REVIEW_COMPONENT_BACKUP"
    if [ -f "$target_file" ]; then
      cp -a "$target_file" "$REVIEW_COMPONENT_BACKUP/$file"
    else
      touch "$REVIEW_COMPONENT_BACKUP/.new-$file"
    fi
    install -o root -g root -m 0644 "$source_file" "$target_file"
    HA_CHANGED=1
    REVIEW_COMPONENT_CHANGED=1
  fi
done
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
JUNK_QUEUE_DIR="$PA_STATE_DIR/junk-requests"
install -d -o joshan -g joshan -m 0700 "$JUNK_QUEUE_DIR"
install -d -o joshan -g joshan -m 0700 "$JUNK_QUEUE_DIR/failed"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/review-requests"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/review-requests/failed"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/task-reviews"
install -d -o joshan -g joshan -m 0700 "$PA_STATE_DIR/task-previews"
systemctl is-active --quiet lifeos-task-reconciler.path
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
    if [ "$REVIEW_COMPONENT_CHANGED" -eq 1 ]; then rollback_review_component; fi
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
    if [ "$REVIEW_COMPONENT_CHANGED" -eq 1 ]; then
      rollback_review_component
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
python3 - <<'PYPROBE'
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

task_id = "runtime-auth-" + uuid.uuid4().hex
marker = "LIFEOS_PRIVATE_PREVIEW_AUTH_PROBE_" + uuid.uuid4().hex
preview_path = Path("/config/lifeos-pa-state/task-previews") / (task_id + ".json")
preview_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
preview_path.write_text(json.dumps({
    "schema": "lifeos_pa_task_previews_v1",
    "task_id": task_id,
    "generated_at": int(time.time()),
    "documents": [{"document_id": "1", "title": "synthetic probe", "ocr_text": marker}],
}), encoding="utf-8")
os.chmod(preview_path, 0o600)
try:
    request = urllib.request.Request(
        "http://127.0.0.1:8123/api/lifeos_pa_review/" + task_id,
        headers={"".join(("Author", "ization")): "Bearer invalid-lifeos-preview-probe"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            body = response.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read(20000).decode("utf-8", "replace")
    leaked = marker in body
    print("PA_REVIEW_PREVIEW_API_HTTP=" + str(status))
    print("PA_REVIEW_PREVIEW_API_MARKER_LEAK=" + ("YES" if leaked else "NO"))
    if status in {401, 403, 404} and not leaked:
        print("PA_REVIEW_PREVIEW_API_AUTH=PASS")
    else:
        print("PA_REVIEW_PREVIEW_API_AUTH=FAIL")
        raise SystemExit(1)
finally:
    preview_path.unlink(missing_ok=True)
PYPROBE
