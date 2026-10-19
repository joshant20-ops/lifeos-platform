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
paperless_runtime_diagnostic() {
  local ids state health state_health http_status reachability
  local published=UNKNOWN container_status=unknown container_health=unknown
  local -a container_ids=()

  if command -v docker >/dev/null 2>&1; then
    if ids="$(timeout 3 docker ps -aq --filter publish=8010 2>/dev/null)"; then
      if [[ -z "$ids" ]]; then
        published=NO
        container_status=none
        container_health=none
      else
        mapfile -t container_ids <<<"$ids"
        published=YES
        if [[ "${#container_ids[@]}" -eq 1 ]]; then
          state_health="$(timeout 3 docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_ids[0]}" 2>/dev/null || true)"
          read -r state health <<<"$state_health"
          case "$state" in
            running|exited|created|restarting|paused|dead|removing) container_status="$state" ;;
            *) container_status=unknown ;;
          esac
          case "$health" in
            healthy|unhealthy|starting|none) container_health="$health" ;;
            *) container_health=unknown ;;
          esac
        else
          container_status=multiple
          container_health=multiple
        fi
      fi
    fi
  fi

  http_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --connect-timeout 2 --max-time 5 http://127.0.0.1:8010/api/ 2>/dev/null || true)"
  if [[ "$http_status" =~ ^[1-5][0-9]{2}$ ]]; then
    reachability=REACHABLE
  else
    http_status=000
    reachability=UNREACHABLE
  fi

  printf 'PAPERLESS_8010_PUBLISHED=%s\n' "$published"
  printf 'PAPERLESS_CONTAINER_STATUS=%s\n' "$container_status"
  printf 'PAPERLESS_CONTAINER_HEALTH=%s\n' "$container_health"
  printf 'PAPERLESS_API_HTTP_STATUS=%s\n' "$http_status"
  printf 'PAPERLESS_API_REACHABILITY=%s\n' "$reachability"
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
