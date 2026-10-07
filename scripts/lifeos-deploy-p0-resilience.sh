#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly BRIDGE_SOURCE="$PLATFORM/governor/ha_issue_queue_bridge.py"
readonly BRIDGE_UNIT_SOURCE="$PLATFORM/governor/systemd/lifeos-ha-issue-queue-bridge.service"
readonly CLOCK_DROPIN_SOURCE="$PLATFORM/governor/systemd/chrony.service.d/10-lifeos-boot-clock.conf"
readonly POWERDOWN_SOURCE="$PLATFORM/homelab/live/usr/local/sbin/lifeos-powerdown-assurance-active"
readonly BRIDGE_DEST=/usr/local/libexec/lifeos-ha-issue-queue-bridge
readonly BRIDGE_UNIT_DEST=/etc/systemd/system/lifeos-ha-issue-queue-bridge.service
readonly CLOCK_DROPIN_DEST=/etc/systemd/system/chrony.service.d/10-lifeos-boot-clock.conf
readonly POWERDOWN_DEST=/usr/local/sbin/lifeos-powerdown-assurance-active
readonly BACKUP_ROOT=/var/backups/lifeos-p0-resilience
readonly GIT=/usr/bin/git

fail() { printf 'P0_DEPLOY=FAIL\nREASON=%s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || fail must_run_as_root
[[ -d "$PLATFORM/.git" ]] || fail platform_checkout_missing
[[ -f "$BRIDGE_SOURCE" && ! -L "$BRIDGE_SOURCE" ]] || fail bridge_source_missing
[[ -f "$BRIDGE_UNIT_SOURCE" && ! -L "$BRIDGE_UNIT_SOURCE" ]] || fail bridge_unit_source_missing
[[ -f "$CLOCK_DROPIN_SOURCE" && ! -L "$CLOCK_DROPIN_SOURCE" ]] || fail clock_dropin_source_missing
[[ -f "$POWERDOWN_SOURCE" && ! -L "$POWERDOWN_SOURCE" ]] || fail powerdown_source_missing

HEAD=$(runuser -u joshan -- "$GIT" -C "$PLATFORM" rev-parse HEAD)
MAIN=$(runuser -u joshan -- "$GIT" -C "$PLATFORM" rev-parse main)
ORIGIN=$(runuser -u joshan -- "$GIT" -C "$PLATFORM" rev-parse origin/main)
STATUS=$(runuser -u joshan -- "$GIT" -C "$PLATFORM" status --porcelain)
[[ "$HEAD" == "$MAIN" && "$HEAD" == "$ORIGIN" && -z "$STATUS" ]] || fail source_not_clean_published_main
python3 -m py_compile "$BRIDGE_SOURCE" "$POWERDOWN_SOURCE" || fail python_compile_failed

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$BACKUP_ROOT/$STAMP"
install -d -o root -g root -m 0700 "$BACKUP"
SUCCESS=0

backup_one() {
  local dest="$1" name="$2"
  if [[ -e "$dest" ]]; then
    cp -a -- "$dest" "$BACKUP/$name"
    printf 'P0_BACKUP_%s=present\n' "$name"
  else
    printf 'P0_BACKUP_%s=absent\n' "$name"
  fi
}

restore_one() {
  local dest="$1" name="$2"
  if [[ -e "$BACKUP/$name" ]]; then
    install -D -o root -g root -m "$(stat -c '%a' "$BACKUP/$name")" "$BACKUP/$name" "$dest"
  else
    rm -f -- "$dest"
  fi
}

rollback() {
  local rc=$?
  if [[ "$SUCCESS" != 1 ]]; then
    set +e
    restore_one "$BRIDGE_DEST" bridge
    restore_one "$BRIDGE_UNIT_DEST" bridge-unit
    restore_one "$CLOCK_DROPIN_DEST" clock-dropin
    restore_one "$POWERDOWN_DEST" powerdown
    systemctl daemon-reload
    systemctl restart chrony.service
    systemctl restart lifeos-ha-issue-queue-bridge.service
    echo 'P0_DEPLOY_ROLLBACK=ATTEMPTED' >&2
  fi
  exit "$rc"
}
trap rollback EXIT

backup_one "$BRIDGE_DEST" bridge
backup_one "$BRIDGE_UNIT_DEST" bridge-unit
backup_one "$CLOCK_DROPIN_DEST" clock-dropin
backup_one "$POWERDOWN_DEST" powerdown

install -o root -g root -m 0755 "$BRIDGE_SOURCE" "$BRIDGE_DEST"
install -o root -g root -m 0644 "$BRIDGE_UNIT_SOURCE" "$BRIDGE_UNIT_DEST"
install -D -o root -g root -m 0644 "$CLOCK_DROPIN_SOURCE" "$CLOCK_DROPIN_DEST"
install -o root -g root -m 0755 "$POWERDOWN_SOURCE" "$POWERDOWN_DEST"
systemctl daemon-reload

systemctl restart chrony.service
systemctl is-active --quiet chrony.service || fail chrony_not_active
chrony_exec=$(systemctl show chrony.service -p ExecStart --value)
[[ "$chrony_exec" == *"chronyd -s"* ]] || fail chrony_boot_recovery_option_missing

systemctl restart lifeos-ha-issue-queue-bridge.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service || fail issue_queue_bridge_not_active
cmp -s "$BRIDGE_SOURCE" "$BRIDGE_DEST" || fail bridge_source_mismatch
cmp -s "$BRIDGE_UNIT_SOURCE" "$BRIDGE_UNIT_DEST" || fail bridge_unit_mismatch
cmp -s "$CLOCK_DROPIN_SOURCE" "$CLOCK_DROPIN_DEST" || fail clock_dropin_mismatch
cmp -s "$POWERDOWN_SOURCE" "$POWERDOWN_DEST" || fail powerdown_source_mismatch

local_operation_probe() {
  local predbat_http
  predbat_http=$(curl --silent --max-time 5 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:5052/ 2>/dev/null || true)
  [[ "$predbat_http" == 302 ]] || fail "predbat_http_$predbat_http"
  python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8110/api/energy/current", timeout=10) as response:
    assert response.status == 200
    data = json.load(response)
assert "grid_import_w" in data and ("retrieved_at" in data or "reading_time" in data)
print("P0_LOCAL_ENERGY=PASS")
PY
  lifeos-secret exec homeassistant.long_lived_access_token HA_TOKEN python3 -c '
import json, os, urllib.request
root="http://127.0.0.1:8123/api/states/"
headers={"Authorization":"Bearer "+os.environ["HA_TOKEN"],"Accept":"application/json"}
for entity in ("predbat.status","sensor.lifeos_grid_import_power","sensor.predbat_enphase_5731818_pv_power"):
    req=urllib.request.Request(root+entity,headers=headers)
    with urllib.request.urlopen(req,timeout=8) as response:
        row=json.load(response)
    assert row.get("state") not in ("unknown","unavailable"), entity
print("P0_LOCAL_HA_ENPHASE=PASS")
'
  echo "P0_PREDBAT_HTTP=$predbat_http"
}

local_operation_probe

readonly WAN_TEST_DIR=/run/systemd/system/lifeos-ha-issue-queue-bridge.service.d
readonly WAN_TEST_DROPIN="$WAN_TEST_DIR/95-p0-wan-acceptance.conf"
remove_wan_test() {
  rm -f "$WAN_TEST_DROPIN"
  rmdir "$WAN_TEST_DIR" 2>/dev/null || true
  systemctl daemon-reload
}
trap 'remove_wan_test; rollback' EXIT
install -d -o root -g root -m 0755 "$WAN_TEST_DIR"
cat >"$WAN_TEST_DROPIN" <<'EOF'
[Service]
IPAddressDeny=any
EOF
systemctl daemon-reload
systemctl restart lifeos-ha-issue-queue-bridge.service
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service || fail bridge_not_running_during_wan_test
wan_started=$(date --iso-8601=seconds)
restarts_after_start=$(systemctl show lifeos-ha-issue-queue-bridge.service -p NRestarts --value)
degraded_seen=0
for _ in $(seq 1 24); do
  if journalctl -u lifeos-ha-issue-queue-bridge.service --since "$wan_started" -o cat --no-pager 2>/dev/null | grep -q 'QUEUE_REFRESH=DEGRADED'; then
    degraded_seen=1
    break
  fi
  sleep 5
done
[[ "$degraded_seen" == 1 ]] || fail bridge_degraded_state_not_observed
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service || fail bridge_stopped_during_wan_loss
restarts_during_loss=$(systemctl show lifeos-ha-issue-queue-bridge.service -p NRestarts --value)
[[ "$restarts_during_loss" == "$restarts_after_start" ]] || fail bridge_restart_during_wan_loss
local_operation_probe
remove_wan_test
systemctl restart lifeos-ha-issue-queue-bridge.service
recovery_started=$(date --iso-8601=seconds)
recovered=0
for _ in $(seq 1 24); do
  if journalctl -u lifeos-ha-issue-queue-bridge.service --since "$recovery_started" -o cat --no-pager 2>/dev/null | grep -q 'QUEUE_REFRESH=PASS'; then
    recovered=1
    break
  fi
  sleep 5
done
[[ "$recovered" == 1 ]] || fail bridge_did_not_recover_with_github
systemctl is-active --quiet lifeos-ha-issue-queue-bridge.service || fail bridge_stopped_after_recovery
python3 -m unittest -v tests.test_p0_cloud_degradation
echo 'P0_WAN_DEGRADATION=PASS'
echo 'P0_WAN_RECOVERY=PASS'
echo 'P0_LOCAL_OPERATION_DURING_WAN_LOSS=PASS'

SUCCESS=1
trap - EXIT
echo 'P0_DEPLOY=PASS'
echo 'P0_CHRONY_BOOT_RECOVERY=PASS'
echo 'P0_QUEUE_BRIDGE_RESTART=PASS'
echo 'P0_POWERDOWN_ACTIVE_DEPLOYED=YES'
echo "P0_SOURCE_COMMIT=$HEAD"
echo "P0_BACKUP=$BACKUP"
