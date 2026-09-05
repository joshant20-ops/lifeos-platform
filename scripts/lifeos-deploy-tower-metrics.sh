#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
METRICS_SOURCE="$PLATFORM/governor/tower_metrics.py"
UNIT_SOURCE="$PLATFORM/systemd/lifeos-tower-metrics.service"
DASHBOARD_ADAPTER="$PLATFORM/scripts/lifeos-adapt-ha-tower-control.sh"
EXPECTED_MAC=40:8d:5c:84:41:64
REMOTE_USER=joshan
MQTT_PORT=1883
STAMP="$(date +%Y%m%d-%H%M%S)"
TMPDIR="$(mktemp -d /tmp/lifeos-tower-metrics.XXXXXX)"
chmod 0755 "$TMPDIR"
REMOTE_BACKUP="/var/backups/lifeos-tower-metrics-$STAMP"
DEPLOY_STARTED=0
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

cleanup() {
  rm -rf "$TMPDIR"
}

rollback() {
  rc=$?
  echo "TOWER_METRICS_ROLLBACK=attempting"
  if [[ "$DEPLOY_STARTED" == 1 && -n "$SSH_TARGET" ]]; then
    "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
      "sudo -n bash -s -- '$REMOTE_BACKUP'" <<'EOS' || true
set -Eeuo pipefail
backup=$1
restore_one() {
  name=$1
  dest=$2
  mode=$3
  if [[ -f "$backup/$name.before" ]]; then
    install -o root -g root -m "$mode" "$backup/$name.before" "$dest"
  elif [[ -f "$backup/$name.absent" ]]; then
    rm -f "$dest"
  fi
}
restore_one tower_metrics.py /usr/local/lib/lifeos/tower_metrics.py 0755
restore_one lifeos-tower-metrics.service /etc/systemd/system/lifeos-tower-metrics.service 0644
restore_one tower-metrics.env /etc/lifeos/tower-metrics.env 0644
systemctl daemon-reload
if [[ -f "$backup/service-was-active" ]]; then
  systemctl enable lifeos-tower-metrics.service >/dev/null 2>&1 || true
  systemctl restart lifeos-tower-metrics.service || true
else
  systemctl disable --now lifeos-tower-metrics.service >/dev/null 2>&1 || true
fi
EOS
  fi
  echo "TOWER_METRICS_ROLLBACK=finished"
  exit "$rc"
}
trap rollback ERR
trap cleanup EXIT

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }
for file in "$METRICS_SOURCE" "$UNIT_SOURCE" "$DASHBOARD_ADAPTER"; do
  [[ -f "$file" && ! -L "$file" ]] || { echo "ERROR=canonical_file_missing:$file"; exit 1; }
done
python3 -m py_compile "$METRICS_SOURCE"

# Resolve the live Tower address from its already-canonical MAC without committing
# a private LAN address to the repository.
TOWER_IP="$(python3 - "$EXPECTED_MAC" <<'PY'
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
)"
if [[ -z "$TOWER_IP" ]]; then
  echo 'ERROR=tower_mac_not_present_in_neighbor_table'
  echo "TOWER_EXPECTED_MAC=$EXPECTED_MAC"
  false
fi
ACTUAL_MAC="$(ip neigh show "$TOWER_IP" | awk '{for(i=1;i<=NF;i++) if($i=="lladdr") print $(i+1)}' | head -n1 | tr '[:upper:]' '[:lower:]')"
[[ "$ACTUAL_MAC" == "$EXPECTED_MAC" ]] || { echo "ERROR=tower_mac_mismatch:$ACTUAL_MAC"; false; }
echo "TOWER_NETWORK_IDENTITY=PASS"
echo "TOWER_MAC=$EXPECTED_MAC"

# Prefer reverse-DNS hostname if it is already trusted in known_hosts; otherwise
# fall back to the discovered IP. Strict host-key checking is never disabled.
REVERSE_HOST="$(getent hosts "$TOWER_IP" 2>/dev/null | awk 'NR==1{print $2}' || true)"
for candidate in "$REVERSE_HOST" "$TOWER_IP"; do
  [[ -n "$candidate" ]] || continue
  target="$REMOTE_USER@$candidate"
  if "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$target" 'printf READY' 2>/dev/null | grep -qx READY; then
    SSH_TARGET="$target"
    break
  fi
done
[[ -n "$SSH_TARGET" ]] || {
  echo 'ERROR=tower_ssh_batch_trusted_path_unavailable'
  echo 'TOWER_SSH_REQUIRES=existing_trusted_host_key_and_noninteractive_key'
  false
}
echo "TOWER_SSH=PASS"

REMOTE_ID="$("${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'printf "%s|%s|%s" "$(hostname)" "$(id -un)" "$(. /etc/os-release; printf %s "$ID:$VERSION_ID")"')"
IFS='|' read -r REMOTE_HOSTNAME REMOTE_ACTOR REMOTE_OS <<<"$REMOTE_ID"
[[ "${REMOTE_HOSTNAME,,}" == towerpc* ]] || { echo "ERROR=unexpected_tower_hostname:$REMOTE_HOSTNAME"; false; }
[[ "$REMOTE_ACTOR" == "$REMOTE_USER" ]] || { echo "ERROR=unexpected_tower_actor:$REMOTE_ACTOR"; false; }
[[ "$REMOTE_OS" == debian:12* ]] || { echo "ERROR=unexpected_tower_os:$REMOTE_OS"; false; }
echo "TOWER_HOST_IDENTITY=PASS"
echo "TOWER_HOSTNAME=$REMOTE_HOSTNAME"
echo "TOWER_OS=$REMOTE_OS"

"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'command -v python3 >/dev/null' || { echo 'ERROR=tower_python3_missing'; false; }
"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'command -v mosquitto_pub >/dev/null' || { echo 'ERROR=tower_mosquitto_pub_missing'; false; }
"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'sudo -n true' || { echo 'ERROR=tower_noninteractive_sudo_unavailable'; false; }
echo 'TOWER_EXISTING_RUNTIME_PREREQS=PASS'

# Use the Pi address on the route to Tower as the broker endpoint. Mosquitto is
# already published on TCP/1883 by the existing compose stack.
BROKER_IP="$(ip -4 route get "$TOWER_IP" | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')"
[[ -n "$BROKER_IP" ]] || { echo 'ERROR=broker_route_source_unresolved'; false; }
ss -ltn | awk '{print $4}' | grep -Eq '(^|:)'"$MQTT_PORT"'$' || { echo 'ERROR=local_mqtt_listener_absent'; false; }

# Prove the Tower can publish to the existing broker before any installation.
PREFLIGHT_TOPIC="lifeos/tower/metrics/deploy_preflight"
"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
  "mosquitto_pub -h '$BROKER_IP' -p '$MQTT_PORT' -t '$PREFLIGHT_TOPIC' -m '$STAMP'" || {
    echo 'ERROR=tower_cannot_publish_to_existing_mqtt_broker'
    echo 'TOWER_MQTT_AUTH_OR_NETWORK_REVIEW=REQUIRED'
    false
  }
echo 'TOWER_MQTT_PUBLISH_PREFLIGHT=PASS'

cp "$METRICS_SOURCE" "$TMPDIR/tower_metrics.py"
cp "$UNIT_SOURCE" "$TMPDIR/lifeos-tower-metrics.service"
cat >"$TMPDIR/tower-metrics.env" <<EOF
LIFEOS_MQTT_HOST=$BROKER_IP
LIFEOS_MQTT_PORT=$MQTT_PORT
LIFEOS_TOWER_METRICS_INTERVAL=15
LIFEOS_TOWER_IDLE_SECONDS=600
EOF
chmod 0644 "$TMPDIR"/*

# Transfer only the three reviewed artifacts to temporary paths on Tower.
"${AS_JOSHAN[@]}" scp "${SSH_OPTS[@]}" \
  "$TMPDIR/tower_metrics.py" "$TMPDIR/lifeos-tower-metrics.service" "$TMPDIR/tower-metrics.env" \
  "$SSH_TARGET:/tmp/"

# Back up the current Tower runtime before mutating it.
"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
  "sudo -n bash -s -- '$REMOTE_BACKUP'" <<'EOS'
set -Eeuo pipefail
backup=$1
mkdir -p "$backup"
backup_one() {
  name=$1
  source=$2
  if [[ -f "$source" ]]; then
    cp -a "$source" "$backup/$name.before"
  else
    : > "$backup/$name.absent"
  fi
}
backup_one tower_metrics.py /usr/local/lib/lifeos/tower_metrics.py
backup_one lifeos-tower-metrics.service /etc/systemd/system/lifeos-tower-metrics.service
backup_one tower-metrics.env /etc/lifeos/tower-metrics.env
if systemctl is-active --quiet lifeos-tower-metrics.service 2>/dev/null; then
  : > "$backup/service-was-active"
fi
EOS
DEPLOY_STARTED=1

"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'sudo -n bash -s' <<'EOS'
set -Eeuo pipefail
mkdir -p /usr/local/lib/lifeos /etc/lifeos
install -o root -g root -m 0755 /tmp/tower_metrics.py /usr/local/lib/lifeos/tower_metrics.py
install -o root -g root -m 0644 /tmp/lifeos-tower-metrics.service /etc/systemd/system/lifeos-tower-metrics.service
install -o root -g root -m 0644 /tmp/tower-metrics.env /etc/lifeos/tower-metrics.env
python3 -m py_compile /usr/local/lib/lifeos/tower_metrics.py
systemctl daemon-reload
systemctl enable lifeos-tower-metrics.service >/dev/null
systemctl restart lifeos-tower-metrics.service
rm -f /tmp/tower_metrics.py /tmp/lifeos-tower-metrics.service /tmp/tower-metrics.env
EOS

for _ in $(seq 1 20); do
  if "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'systemctl is-active --quiet lifeos-tower-metrics.service'; then
    break
  fi
  sleep 1
done
"${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'systemctl is-active --quiet lifeos-tower-metrics.service' || {
  echo 'ERROR=tower_metrics_service_not_active'
  "${AS_JOSHAN[@]}" ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'journalctl -u lifeos-tower-metrics.service -n 30 --no-pager' || true
  false
}
echo 'TOWER_METRICS_SERVICE=ACTIVE'

# Observe a real payload from the existing local broker; do not accept discovery
# alone as proof that the agent works.
PAYLOAD="$(timeout 45s mosquitto_sub -h 127.0.0.1 -p "$MQTT_PORT" -C 1 -t lifeos/tower/metrics)"
[[ -n "$PAYLOAD" ]] || { echo 'ERROR=tower_metrics_payload_absent'; false; }
VALIDATION="$(python3 - "$PAYLOAD" <<'PY'
import json,sys
p=json.loads(sys.argv[1])
for key in ('cpu_percent','ram_percent','load_1m','net_rx_mb_s','net_tx_mb_s','activity','disks','gpu'):
    if key not in p:
        raise SystemExit('ERROR=metrics_field_missing:' + key)
if p['activity'] not in {'QUIET','IDLE','ACTIVE','HEAVY'}:
    raise SystemExit('ERROR=invalid_activity_state')
if not isinstance(p['disks'],dict) or not p['disks']:
    raise SystemExit('ERROR=no_physical_disks_reported')
for name,d in p['disks'].items():
    if 'read_mb_s' not in d or 'write_mb_s' not in d:
        raise SystemExit('ERROR=disk_rate_missing:' + name)
print('TOWER_METRICS_PAYLOAD=PASS')
print('TOWER_METRICS_ACTIVITY=' + p['activity'])
print('TOWER_METRICS_DISKS=' + ','.join(sorted(p['disks'])))
print('TOWER_GPU_AVAILABLE=' + ('YES' if bool(p.get('gpu',{}).get('available')) else 'NO'))
PY
)"
printf '%s\n' "$VALIDATION"

# Wait for Home Assistant MQTT discovery to register both the fixed telemetry set
# and at least one physical disk's read + write entities.
COUNT=0
DISK_COUNT=0
for _ in $(seq 1 30); do
  REGISTRY_COUNTS="$(docker exec -i homeassistant python3 - <<'PY'
import json
from pathlib import Path
p=Path('/config/.storage/core.entity_registry')
if not p.exists():
    print('0|0'); raise SystemExit
ents=json.loads(p.read_text()).get('data',{}).get('entities',[])
uids=[str(e.get('unique_id') or '') for e in ents]
metrics=[u for u in uids if u.startswith('lifeos_tower_') and u.endswith('_v1')]
disk_rates=[u for u in metrics if u.startswith('lifeos_tower_disk_') and (u.endswith('_read_v1') or u.endswith('_write_v1'))]
print(f'{len(metrics)}|{len(disk_rates)}')
PY
)"
  IFS='|' read -r COUNT DISK_COUNT <<<"$REGISTRY_COUNTS"
  if (( COUNT >= 10 && DISK_COUNT >= 2 )); then
    break
  fi
  sleep 2
done
(( COUNT >= 10 )) || { echo "ERROR=ha_metrics_discovery_incomplete:$COUNT"; false; }
(( DISK_COUNT >= 2 )) || { echo "ERROR=ha_disk_rate_discovery_incomplete:$DISK_COUNT"; false; }
echo "TOWER_HA_METRICS_ENTITY_COUNT=$COUNT"
echo "TOWER_HA_DISK_RATE_ENTITY_COUNT=$DISK_COUNT"

# Rebuild the dedicated view now that actual disk entity IDs exist.
bash "$DASHBOARD_ADAPTER"

# Prove the live Z97 view contains graphs and at least one physical-disk graph.
docker exec -i homeassistant python3 - <<'PY'
import json
from pathlib import Path
doc=json.loads(Path('/config/.storage/lovelace.lifeos_control').read_text())
views=doc.get('data',{}).get('config',{}).get('views',[])
z97=next((v for v in views if v.get('path')=='z97'),None)
if not z97:
    raise SystemExit('ERROR=z97_view_missing')
cards=z97.get('cards',[])
history=[c for c in cards if c.get('type')=='history-graph']
disk_history=[c for c in history if str(c.get('title') or '').startswith('Disk ')]
if len(history) < 5:
    raise SystemExit('ERROR=z97_history_graphs_incomplete:' + str(len(history)))
if not disk_history:
    raise SystemExit('ERROR=z97_disk_graph_missing')
print('Z97_METRICS_VIEW=PASS')
print('Z97_HISTORY_GRAPHS=' + str(len(history)))
print('Z97_DISK_GRAPHS=' + str(len(disk_history)))
PY

DEPLOY_STARTED=0
echo 'RESULT=PASS'
echo 'TOWER_METRICS_DEPLOYED=YES'
echo 'TOWER_METRICS_TRANSPORT=MQTT_EXISTING_BROKER'
echo 'TOWER_METRICS_INTERVAL_SECONDS=15'
echo 'TOWER_IDLE_WINDOW_SECONDS=600'
echo "TOWER_METRICS_REMOTE_BACKUP=$REMOTE_BACKUP"
echo 'TOWER_METRICS_ROLLBACK=backup_preserved'
