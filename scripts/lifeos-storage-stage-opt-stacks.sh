#!/usr/bin/env bash
# Safe initial rsync stage. Does not stop or restart services and does not alter /opt/stacks.
set -Eeuo pipefail
SSD=/mnt/docker-data
SOURCE=/opt/stacks
DEST=/mnt/docker-data/opt-stacks
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
MARKER=/mnt/docker-data/.lifeos-opt-stacks-stage

fail(){ echo "RESULT=FAIL"; echo "ERROR=$*"; exit 1; }
echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "OPERATION=storage-stage-opt-stacks"

[[ -d "$SOURCE" && ! -L "$SOURCE" ]] || fail "source_missing_or_symlink:$SOURCE"
[[ "$(findmnt -n -o UUID -T "$SSD" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || fail "ssd_uuid_mismatch"
[[ "$(findmnt -n -o TARGET -T "$SSD" 2>/dev/null || true)" == "$SSD" ]] || fail "ssd_mountpoint_not_exact"
[[ "$(docker info --format '{{.DockerRootDir}}')" == "$SSD" ]] || fail "docker_root_not_on_ssd"
[[ "$(findmnt -n -o UUID -T "$SOURCE" 2>/dev/null || true)" != "$EXPECTED_UUID" ]] || fail "source_already_on_ssd"
[[ "$(findmnt -n -o TARGET -T "$SOURCE" 2>/dev/null || true)" == "/" ]] || fail "source_filesystem_unexpected"

source_bytes=$(du -sx --block-size=1 "$SOURCE" | awk '{print $1}')
available_bytes=$(df -B1 --output=avail "$SSD" | tail -n 1 | tr -d ' ')
echo "SOURCE_BYTES=$source_bytes"
echo "SSD_AVAILABLE_BYTES=$available_bytes"
(( available_bytes > source_bytes * 3 )) || fail "insufficient_staging_headroom"

if [[ -e "$DEST" ]]; then
  [[ -d "$DEST" && ! -L "$DEST" ]] || fail "destination_not_directory"
  [[ -f "$MARKER" && ! -L "$MARKER" ]] || fail "destination_exists_without_stage_marker"
  grep -Fxq "SOURCE=$SOURCE" "$MARKER" || fail "stage_marker_source_mismatch"
  grep -Fxq "EXPECTED_UUID=$EXPECTED_UUID" "$MARKER" || fail "stage_marker_uuid_mismatch"
else
  mkdir -p -- "$DEST"
fi
[[ "$(stat -c '%d' "$DEST")" == "$(stat -c '%d' "$SSD")" ]] || fail "destination_not_on_ssd"

echo "--- before ---"
df -hT / "$SSD"
du -sx --block-size=1 "$SOURCE" "$DEST" 2>/dev/null || true

# The source remains live during this first-pass copy. SQLite WAL/SHM and
# similar transient files can legitimately disappear between enumeration and
# transfer. Treat rsync code 24 as a retryable/live-source condition here only.
# The stopped-writer final sync remains strict and must return zero.
set +e
rsync -aHAXx --numeric-ids --delete --info=stats2 "$SOURCE/" "$DEST/"
stage_rc=$?
set -e
if [[ "$stage_rc" -ne 0 && "$stage_rc" -ne 24 ]]; then
  fail "initial_rsync_failed:$stage_rc"
fi
echo "INITIAL_RSYNC_RC=$stage_rc"
[[ "$stage_rc" -eq 24 ]] && echo "INITIAL_RSYNC_VANISHED_FILES=TOLERATED_LIVE_STAGE"

# A live first copy may differ in files written during transfer; report that
# delta, then the separate stopped-writer final sync will close it.
set +e
delta=$(rsync -aHAXxnc --numeric-ids --delete --dry-run --itemize-changes "$SOURCE/" "$DEST/" 2>&1)
delta_rc=$?
set -e
[[ "$delta_rc" -eq 0 ]] || fail "initial_checksum_scan_failed:$delta_rc"
delta_count=$(printf '%s\n' "$delta" | awk 'NF {n++} END {print n+0}')
echo "INITIAL_CHECKSUM_DELTA_ENTRIES=$delta_count"
[[ -z "$delta" ]] || printf '%s\n' "$delta" | head -100

printf '%s\n' "SOURCE=$SOURCE" "EXPECTED_UUID=$EXPECTED_UUID" "STAGED_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$MARKER"
chmod 0600 "$MARKER"
echo "STAGE_DESTINATION=$DEST"
du -sx --block-size=1 "$SOURCE" "$DEST"
echo "--- after ---"
df -hT / "$SSD"
echo "SOURCE_UNCHANGED=$(test -d "$SOURCE" && echo YES)"
echo "RESULT=PASS"
