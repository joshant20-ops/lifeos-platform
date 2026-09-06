#!/usr/bin/env bash
set -Eeuo pipefail

BROKER=127.0.0.1
COMMAND_TOPIC=lifeos/tower/power/set
STATE_TOPIC=lifeos/tower/state

state() {
  timeout 5s mosquitto_sub -h "$BROKER" -C 1 -t "$STATE_TOPIC" 2>/dev/null || true
}

is_accessible() {
  python3 - "$1" <<'PY' >/dev/null 2>&1
import json,sys
value=json.loads(sys.argv[1])
raise SystemExit(0 if value.get('accessible') is True else 1)
PY
}

before="$(state)"
is_accessible "$before" || { echo 'ERROR=tower_not_accessible_before_shutdown_proof'; exit 1; }

mosquitto_pub -h "$BROKER" -t "$COMMAND_TOPIC" -m OFF
echo 'TOWER_SHUTDOWN_COMMAND=PUBLISHED'

stopped=0
for _ in $(seq 1 90); do
  current="$(state)"
  if [[ -n "$current" ]] && ! is_accessible "$current"; then
    stopped=1
    break
  fi
  sleep 2
done
[[ "$stopped" == 1 ]] || { echo 'ERROR=tower_remained_accessible_after_shutdown'; exit 1; }
echo 'TOWER_SHUTDOWN_END_TO_END=PASS'

mosquitto_pub -h "$BROKER" -t "$COMMAND_TOPIC" -m ON
echo 'TOWER_WAKE_COMMAND=PUBLISHED'

restored=0
for _ in $(seq 1 90); do
  current="$(state)"
  if [[ -n "$current" ]] && is_accessible "$current"; then
    restored=1
    break
  fi
  sleep 2
done
[[ "$restored" == 1 ]] || { echo 'ERROR=tower_not_accessible_after_wol_recovery'; exit 1; }
echo 'TOWER_WOL_RECOVERY=PASS'
echo 'TOWER_SHUTDOWN_PROOF=PASS'
echo 'TOWER_FINAL_STATE=ACCESSIBLE'

