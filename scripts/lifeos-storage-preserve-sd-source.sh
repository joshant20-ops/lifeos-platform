#!/usr/bin/env bash
# Fixed additive recovery: no cutover, restart, source edits or reboot.
set -Eeuo pipefail
[[ $# -eq 0 && $EUID -eq 0 && $(hostname) == Docker ]] || exit 64
exec /usr/bin/unshare --mount --propagation private /usr/bin/bash -s <<'PRIVATE_NAMESPACE'
set -Eeuo pipefail
umask 077
fail(){ echo "RECOVERY_ERROR=$1"; echo 'RESULT=FAIL'; exit 1; }
trap 'echo RECOVERY_FAILURE_PRESERVES_PARTIAL_DATA=YES' ERR
SSD=/mnt/docker-data
RECOVERY=$SSD/recovery
EXPECTED=a53fd6a0-c498-4b76-a496-0e5d9233447f
[[ $(findmnt -n -o UUID -T /) == e20b40e9-a03b-4e15-b170-f527cf96d5e5 ]] || fail root_uuid
[[ $(findmnt -n -o UUID -T "$SSD") == "$EXPECTED" ]] || fail ssd_uuid
[[ $(findmnt -n -o TARGET -T "$SSD") == "$SSD" ]] || fail ssd_mount
[[ $(findmnt -n -o UUID -T /opt/stacks) == "$EXPECTED" ]] || fail live_stack_uuid
[[ $(docker info --format '{{.DockerRootDir}}') == "$SSD" ]] || fail docker_root
command -v rsync >/dev/null || fail rsync_missing
# Capture host-visible topology before creating namespace-only mounts.
before=$(findmnt -n -o SOURCE,UUID,OPTIONS -T /opt/stacks)
if [[ ! -e "$RECOVERY" && ! -L "$RECOVERY" ]]; then
  mkdir -m 0700 "$RECOVERY"
fi
[[ -d "$RECOVERY" && ! -L "$RECOVERY" ]] || fail recovery_unsafe
[[ $(stat -c '%u:%a' "$RECOVERY") == 0:700 ]] || fail recovery_permissions
[[ $(findmnt -n -o UUID -T "$RECOVERY") == "$EXPECTED" ]] || fail recovery_device
exec 9>"$RECOVERY/.preserve.lock"
flock -n 9 || fail already_running
view=$(mktemp -d /run/lifeos-sd-view.XXXXXX)
cleanup(){ umount "$view" 2>/dev/null || true; rmdir "$view" 2>/dev/null || true; }
trap cleanup EXIT
# Nonrecursive bind intentionally excludes the SSD /opt/stacks submount.
mount --bind / "$view"
mount -o remount,bind,ro "$view"
src=$view/opt/stacks
[[ $(findmnt -n -o UUID -T "$src") == e20b40e9-a03b-4e15-b170-f527cf96d5e5 ]] || fail source_device
[[ ,$(findmnt -n -o OPTIONS -T "$src"), == *,ro,* ]] || fail source_not_readonly
[[ -d "$src" && ! -L "$src" && -f "$src/homeassistant/docker-compose.yml" ]] || fail source_missing
needed=$(du -sx --apparent-size --block-size=1 "$src" | awk '{print $1}')
available=$(df --output=avail -B1 "$RECOVERY" | tail -1 | tr -d ' ')
[[ $needed =~ ^[0-9]+$ && $available =~ ^[0-9]+$ ]] || fail capacity_unknown
(( available > needed + 5368709120 )) || fail insufficient_capacity
dest=$RECOVERY/sd-opt-stacks-20261017
if [[ -e "$dest" || -L "$dest" ]]; then
  [[ -d "$dest" && ! -L "$dest" && -f "$dest/.lifeos-preserved" ]] || fail existing_unverified_destination
  # Marker lives outside the mirrored payload.
  payload=$dest/payload
else
  dest=$(mktemp -d "$RECOVERY/.sd-opt-stacks-partial.XXXXXX")
  payload=$dest/payload
  mkdir -m 0700 "$payload"
  # No --delete on the copying pass. Diagnostics and all contents stay private.
  timeout 1200 rsync -aHAXxS --numeric-ids "$src/" "$payload/" >"$dest/copy.log" 2>&1 || fail copy_failed_partial_retained
fi
# Two checksum/metadata passes detect unstable source as well as incomplete copy.
for pass in 1 2; do
  timeout 1200 rsync -aHAXxnc --numeric-ids --delete --dry-run --itemize-changes "$src/" "$payload/" >"$dest/verify-$pass.log" 2>&1 || fail checksum_scan
  [[ ! -s "$dest/verify-$pass.log" ]] || fail checksum_or_metadata_mismatch
done
[[ "$before" == "$(findmnt -n -o SOURCE,UUID,OPTIONS -T /opt/stacks)" ]] || fail live_mount_changed
[[ $(docker info --format '{{.DockerRootDir}}') == "$SSD" ]] || fail docker_root_changed
printf 'SOURCE_UUID=%s\nCOPY_CHECKSUM_AND_METADATA=PASS\nUTC=%s\n' e20b40e9-a03b-4e15-b170-f527cf96d5e5 "$(date -u +%FT%TZ)" >"$dest/.lifeos-preserved"
sync -f "$dest"
if [[ "$dest" != "$RECOVERY/sd-opt-stacks-20261017" ]]; then
  [[ ! -e "$RECOVERY/sd-opt-stacks-20261017" && ! -L "$RECOVERY/sd-opt-stacks-20261017" ]] || fail destination_race
  mv -T -n "$dest" "$RECOVERY/sd-opt-stacks-20261017"
  [[ ! -e "$dest" ]] || fail publication_not_completed
fi
echo 'SD_SOURCE_READ_ONLY=PASS'
echo 'SD_SOURCE_PRESERVATION=PASS'
echo 'SD_SOURCE_CHECKSUM_METADATA_TWO_PASSES=PASS'
echo 'LIVE_MOUNT_UNCHANGED=PASS'
echo 'RECOVERY_MUTATIONS=ADDITIVE_SSD_COPY_ONLY'
echo 'RESULT=PASS'
PRIVATE_NAMESPACE
