#!/usr/bin/env bash
# Reclaim the temporary SD rollback copy only after the reboot validation has passed.
set -Eeuo pipefail
SSD=/mnt/docker-data
SOURCE=/opt/stacks
ROLLBACK=/opt/stacks.sd-rollback-20261017
DEST=/mnt/docker-data/rollback/opt-stacks-pre-migration
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
STATE=/var/lib/lifeos-storage-migration
[[ "$(findmnt -n -o UUID -T "$SSD" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || { echo "RESULT=FAIL"; echo "ERROR=ssd_uuid_mismatch"; exit 1; }
[[ "$(findmnt -n -o UUID -T "$SOURCE" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || { echo "RESULT=FAIL"; echo "ERROR=opt_stacks_not_ssd_bound"; exit 1; }
[[ -f "$STATE/boot-validation.pass" ]] || { echo "RESULT=FAIL"; echo "ERROR=boot_validation_not_recorded"; exit 1; }
[[ -d "$ROLLBACK" && ! -L "$ROLLBACK" ]] || { echo "RESULT=FAIL"; echo "ERROR=sd_rollback_copy_missing"; exit 1; }
if [[ -e "$DEST" ]]; then echo "RESULT=FAIL"; echo "ERROR=ssd_rollback_destination_exists"; exit 1; fi
mkdir -p "$(dirname "$DEST")"
rsync -aHAXx --numeric-ids "$ROLLBACK/" "$DEST/"
set +e
delta=$(rsync -aHAXxnc --numeric-ids --dry-run --itemize-changes "$ROLLBACK/" "$DEST/" 2>&1)
rc=$?
set -e
[[ "$rc" -eq 0 && -z "$delta" ]] || { echo "$delta"; echo "RESULT=FAIL"; echo "ERROR=rollback_archive_verification_failed"; exit 1; }
echo "ROLLBACK_ARCHIVE=$DEST"
echo "ROLLBACK_BYTES=$(du -sx --block-size=1 "$DEST" | awk '{print $1}')"
rm -rf --one-file-system -- "$ROLLBACK"
[[ ! -e "$ROLLBACK" ]] || { echo "RESULT=FAIL"; echo "ERROR=sd_rollback_copy_remains"; exit 1; }
echo "SD_AFTER=$(df -hT / | tail -n 1)"
echo "SSD_AFTER=$(df -hT "$SSD" | tail -n 1)"
echo "RESULT=PASS"
