#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
SOURCE="$PLATFORM/governor/ha_issue_queue_bridge.py"
DEST=/usr/local/libexec/lifeos-ha-issue-queue-bridge
UNIT=lifeos-ha-issue-queue-bridge.service
DASHBOARD_ADAPTER="$PLATFORM/scripts/lifeos-adapt-ha-lifeos-dashboard.sh"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/mnt/docker-data/automation/backups/ha-control-bridge-$STAMP"

rollback() {
  rc=$?
  if (( rc == 0 )); then return; fi
  echo "ROLLBACK=attempting"
  if [[ -f "$BACKUP/lifeos-ha-issue-queue-bridge.before" ]]; then
    install -o root -g root -m 0755 "$BACKUP/lifeos-ha-issue-queue-bridge.before" "$DEST" || true
    systemctl restart "$UNIT" || true
  fi
  exit "$rc"
}
trap rollback ERR

[[ $EUID -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || { echo 'ERROR=canonical_bridge_missing'; exit 1; }
[[ -f "$DEST" && ! -L "$DEST" ]] || { echo 'ERROR=installed_bridge_missing'; exit 1; }
[[ -f "$DASHBOARD_ADAPTER" && ! -L "$DASHBOARD_ADAPTER" ]] || { echo 'ERROR=dashboard_adapter_missing'; exit 1; }

mkdir -p "$BACKUP"
cp -a "$DEST" "$BACKUP/lifeos-ha-issue-queue-bridge.before"

python3 -m py_compile "$SOURCE"
install -o root -g root -m 0755 "$SOURCE" "$DEST"
systemctl restart "$UNIT"

for _ in $(seq 1 20); do
  if systemctl is-active --quiet "$UNIT"; then break; fi
  sleep 1
done
systemctl is-active --quiet "$UNIT" || { echo 'ERROR=bridge_not_active'; false; }

CONTROL="$(timeout 15s mosquitto_sub -h 127.0.0.1 -C 1 -t lifeos/issue_queue/control 2>/dev/null || true)"
[[ -n "$CONTROL" ]] || { echo 'ERROR=control_topic_absent'; false; }

python3 - "$CONTROL" <<'PY'
import json, sys
value=json.loads(sys.argv[1])
required={'state','github_runner','semaphore','roadmap_stage','roadmap_progress_percent','open_issue_count','eligible_count','blocked_count'}
missing=sorted(required-set(value))
if missing:
    raise SystemExit('missing_control_fields=' + ','.join(missing))
if value['state'] not in {'WORKING','IDLE','BLOCKED','STALLED','DEGRADED'}:
    raise SystemExit('invalid_control_state=' + str(value['state']))
print('CONTROL_STATE=' + value['state'])
print('CONTROL_CURRENT_ISSUE=' + str(value.get('current_issue') or 'none'))
print('CONTROL_BLOCKER=' + str(value.get('blocker') or 'none'))
print('CONTROL_NEXT_ACTION=' + str(value.get('next_action') or 'none'))
print('CONTROL_ROADMAP=' + str(value.get('roadmap_stage')) + '/' + str(value.get('roadmap_stages')))
PY

echo '==> ADAPT CURRENT LIFEOS DASHBOARD'
bash "$DASHBOARD_ADAPTER"

echo 'RESULT=PASS'
echo 'HA_CONTROL_BRIDGE_DEPLOYED=YES'
echo 'MQTT_CONTROL_TOPIC=PASS'
echo 'HOME_ASSISTANT_DEVICE=LifeOS Issue Queue'
echo 'LIFEOS_CONTROL_DASHBOARD=ADAPTED'
echo 'LIFEOS_CONTROL_DASHBOARD_PATH=/lifeos-control/overview'
echo "BACKUP=$BACKUP"
echo 'ROLLBACK=restore backup bridge and dashboard storage backups then restart affected services'
