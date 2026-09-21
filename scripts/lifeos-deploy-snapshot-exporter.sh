#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
SERVICE_SOURCE="$PLATFORM/governor/systemd/lifeos-snapshots-export.service"
TIMER_SOURCE="$PLATFORM/governor/systemd/lifeos-snapshots-export.timer"
SNAPSHOT_SCRIPT="$PLATFORM/governor/scripts/snapshot-lifeos-observed-state.sh"
SNAPSHOT_REPO=/home/joshan/lifeos-snapshots
LATEST="$SNAPSHOT_REPO/snapshots/Docker/latest.json"
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'SNAPSHOT_EXPORT_DEPLOY=FAIL'; echo 'REASON=must_run_as_root'; exit 1; }
for file in "$SERVICE_SOURCE" "$TIMER_SOURCE" "$SNAPSHOT_SCRIPT"; do [[ -f "$file" && ! -L "$file" ]] || { echo "REASON=canonical_source_missing:$file"; exit 1; }; done
install -o root -g root -m 0644 "$SERVICE_SOURCE" /etc/systemd/system/lifeos-snapshots-export.service
install -o root -g root -m 0644 "$TIMER_SOURCE" /etc/systemd/system/lifeos-snapshots-export.timer
systemctl daemon-reload
systemctl enable --now lifeos-snapshots-export.timer
systemctl start lifeos-snapshots-export.service
test "$(systemctl show -p Result --value lifeos-snapshots-export.service)" = success
systemctl is-active --quiet lifeos-snapshots-export.timer
runuser -u joshan -- git -C "$SNAPSHOT_REPO" fetch origin main
test "$(runuser -u joshan -- git -C "$SNAPSHOT_REPO" rev-parse HEAD)" = "$(runuser -u joshan -- git -C "$SNAPSHOT_REPO" rev-parse origin/main)"
age="$(( $(date +%s) - $(stat -c %Y "$LATEST") ))"
test "$age" -lt 300
echo 'SNAPSHOT_EXPORT_DEPLOY=PASS'
echo 'SNAPSHOT_EXPORT=PASS'
echo 'SNAPSHOT_TIMER=ACTIVE'
echo 'SNAPSHOT_FRESHNESS=PASS'
