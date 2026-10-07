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

SUCCESS=1
trap - EXIT
echo 'P0_DEPLOY=PASS'
echo 'P0_CHRONY_BOOT_RECOVERY=PASS'
echo 'P0_QUEUE_BRIDGE_RESTART=PASS'
echo 'P0_POWERDOWN_ACTIVE_DEPLOYED=YES'
echo "P0_SOURCE_COMMIT=$HEAD"
echo "P0_BACKUP=$BACKUP"
