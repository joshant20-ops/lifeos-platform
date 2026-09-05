#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
DEPLOY="$PLATFORM/scripts/lifeos-deploy-tower-metrics.sh"
BASE_DASHBOARD="$PLATFORM/scripts/lifeos-adapt-ha-lifeos-dashboard.sh"
DIAGNOSTICS="$PLATFORM/scripts/lifeos-tower-metrics-live-diagnostics.sh"
EXPECTED_MAC=40:8d:5c:84:41:64
EXPECTED_HOST=TowerPC.Tailor
REMOTE_USER=joshan
PACKAGE=mosquitto-clients
INSTALLED_HERE=0
SSH_TARGET=''

AS_JOSHAN=(
  /usr/sbin/runuser -u joshan -- /usr/bin/env -i
  HOME=/home/joshan
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  LANG=C.UTF-8
)
SSH_OPTS=(
  -o BatchMode=yes
  -o IdentitiesOnly=no
  -o StrictHostKeyChecking=yes
  -o ConnectTimeout=5
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=2
)

rollback_package() {
  rc=$?
  if [[ "$INSTALLED_HERE" == 1 && -n "$SSH_TARGET" ]]; then
    echo 'TOWER_MQTT_CLIENT_ROLLBACK=attempting'
    "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
      "sudo -n apt-get remove -y '$PACKAGE'" || true
    echo 'TOWER_MQTT_CLIENT_ROLLBACK=finished'
  fi
  exit "$rc"
}
trap rollback_package ERR

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
[[ -f "$DEPLOY" && ! -L "$DEPLOY" ]] || { echo 'ERROR=canonical_tower_metrics_deploy_missing'; exit 1; }
[[ -f "$BASE_DASHBOARD" && ! -L "$BASE_DASHBOARD" ]] || { echo 'ERROR=canonical_lifeos_dashboard_adapter_missing'; exit 1; }
[[ -f "$DIAGNOSTICS" && ! -L "$DIAGNOSTICS" ]] || { echo 'ERROR=canonical_tower_metrics_diagnostics_missing'; exit 1; }

find_tower_by_mac() {
  python3 - "$EXPECTED_MAC" <<'PY'
import json, subprocess, sys
mac=sys.argv[1].lower()
try:
    rows=json.loads(subprocess.check_output(['ip','-j','neigh'], text=True))
except Exception:
    rows=[]
for row in rows:
    if str(row.get('lladdr') or '').lower() == mac and ':' not in str(row.get('dst') or ''):
        print(row['dst'])
        break
PY
}

# A sleeping host naturally ages out of the neighbour table. First resolve its
# canonical LAN hostname and probe it to repopulate ARP. If still absent, send the
# already-proven WOL packet and wait for the same hostname/IP to return. Identity
# is never accepted until the observed neighbour MAC matches EXPECTED_MAC.
TOWER_IP="$(find_tower_by_mac)"
HOST_IP="$(getent ahostsv4 "$EXPECTED_HOST" 2>/dev/null | awk 'NR==1{print $1}' || true)"
if [[ -z "$TOWER_IP" && -n "$HOST_IP" ]]; then
  ping -c 1 -W 1 "$HOST_IP" >/dev/null 2>&1 || true
  sleep 1
  ACTUAL_MAC="$(ip neigh show "$HOST_IP" | awk '{for(i=1;i<=NF;i++) if($i=="lladdr") print $(i+1)}' | head -n1 | tr '[:upper:]' '[:lower:]')"
  if [[ "$ACTUAL_MAC" == "$EXPECTED_MAC" ]]; then
    TOWER_IP="$HOST_IP"
  fi
fi

if [[ -z "$TOWER_IP" ]]; then
  command -v wakeonlan >/dev/null || { echo 'ERROR=wakeonlan_missing_on_deploy_host'; false; }
  echo 'TOWER_WAKE=REQUESTED'
  wakeonlan "$EXPECTED_MAC"
  for _ in $(seq 1 45); do
    HOST_IP="$(getent ahostsv4 "$EXPECTED_HOST" 2>/dev/null | awk 'NR==1{print $1}' || true)"
    if [[ -n "$HOST_IP" ]]; then
      ping -c 1 -W 1 "$HOST_IP" >/dev/null 2>&1 || true
      ACTUAL_MAC="$(ip neigh show "$HOST_IP" | awk '{for(i=1;i<=NF;i++) if($i=="lladdr") print $(i+1)}' | head -n1 | tr '[:upper:]' '[:lower:]')"
      if [[ "$ACTUAL_MAC" == "$EXPECTED_MAC" ]]; then
        TOWER_IP="$HOST_IP"
        break
      fi
    fi
    TOWER_IP="$(find_tower_by_mac)"
    [[ -n "$TOWER_IP" ]] && break
    sleep 2
  done
fi

[[ -n "$TOWER_IP" ]] || { echo 'ERROR=tower_not_reachable_after_wol'; false; }
ACTUAL_MAC="$(ip neigh show "$TOWER_IP" | awk '{for(i=1;i<=NF;i++) if($i=="lladdr") print $(i+1)}' | head -n1 | tr '[:upper:]' '[:lower:]')"
[[ "$ACTUAL_MAC" == "$EXPECTED_MAC" ]] || { echo "ERROR=tower_mac_mismatch:$ACTUAL_MAC"; false; }
echo 'TOWER_NETWORK_IDENTITY=PASS'
echo "TOWER_IP=$TOWER_IP"

REVERSE_HOST="$(getent hosts "$TOWER_IP" 2>/dev/null | awk 'NR==1{print $2}' || true)"
for candidate in "$EXPECTED_HOST" "$REVERSE_HOST" "$TOWER_IP"; do
  [[ -n "$candidate" ]] || continue
  target="$REMOTE_USER@$candidate"
  if "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$target" 'printf READY' 2>/dev/null | grep -qx READY; then
    SSH_TARGET="$target"
    break
  fi
done
[[ -n "$SSH_TARGET" ]] || { echo 'ERROR=tower_ssh_batch_trusted_path_unavailable'; false; }

REMOTE_ID="$("${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'printf "%s|%s|%s" "$(hostname)" "$(id -un)" "$(. /etc/os-release; printf %s "$ID:$VERSION_ID")"')"
IFS='|' read -r REMOTE_HOSTNAME REMOTE_ACTOR REMOTE_OS <<<"$REMOTE_ID"
[[ "${REMOTE_HOSTNAME,,}" == towerpc* ]] || { echo "ERROR=unexpected_tower_hostname:$REMOTE_HOSTNAME"; false; }
[[ "$REMOTE_ACTOR" == "$REMOTE_USER" ]] || { echo "ERROR=unexpected_tower_actor:$REMOTE_ACTOR"; false; }
[[ "$REMOTE_OS" == debian:12* ]] || { echo "ERROR=unexpected_tower_os:$REMOTE_OS"; false; }
"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'sudo -n true' || { echo 'ERROR=tower_noninteractive_sudo_unavailable'; false; }
echo 'TOWER_MQTT_CLIENT_IDENTITY=PASS'

if "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'command -v mosquitto_pub >/dev/null'; then
  echo 'TOWER_MQTT_CLIENT=ALREADY_PRESENT'
else
  echo "TOWER_MQTT_CLIENT=INSTALLING_EXACT_PACKAGE:$PACKAGE"
  "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
    "sudo -n apt-get update && sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends '$PACKAGE'"
  INSTALLED_HERE=1
  "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'command -v mosquitto_pub >/dev/null' || {
    echo 'ERROR=tower_mosquitto_pub_missing_after_install'
    false
  }
  echo 'TOWER_MQTT_CLIENT=INSTALLED'
fi

bash "$BASE_DASHBOARD"
echo 'TOWER_DASHBOARD_BASELINE=PASS'

bash "$DEPLOY"
bash "$DIAGNOSTICS"

INSTALLED_HERE=0
echo 'TOWER_MQTT_CLIENT_PREREQ=PASS'
echo 'RESULT=PASS'
