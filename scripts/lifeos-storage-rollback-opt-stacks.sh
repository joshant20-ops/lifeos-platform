#!/usr/bin/env bash
# Explicit operator rollback to the retained pre-migration SD tree.
set -Eeuo pipefail
SSD=/mnt/docker-data
SOURCE=/opt/stacks
ROLLBACK=/opt/stacks.sd-rollback-20261017
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
STATE=/var/lib/lifeos-storage-migration
FSTAB=/etc/fstab
DROPIN=/etc/systemd/system/docker.service.d/20-lifeos-storage.conf
GUARD=/usr/local/sbin/lifeos-require-opt-stacks-ssd
[[ "$(findmnt -n -o UUID -T "$SSD" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || { echo "RESULT=FAIL"; echo "ERROR=ssd_uuid_mismatch"; exit 1; }
[[ -f "$STATE/fstab.before" && -d "$ROLLBACK" ]] || { echo "RESULT=FAIL"; echo "ERROR=rollback_prerequisite_missing"; exit 1; }
[[ "$(findmnt -n -o UUID -T "$SOURCE" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || { echo "RESULT=FAIL"; echo "ERROR=opt_stacks_not_currently_ssd_bound"; exit 1; }
mapfile -t ids < <(docker ps -q)
if (("${#ids[@]}")); then docker stop --time 90 "${ids[@]}"; fi
systemctl stop docker.service
umount "$SOURCE"
cp -a "$STATE/fstab.before" "$FSTAB"
if [[ -f "$STATE/docker-dropin.before" ]]; then install -D -o root -g root -m 0644 "$STATE/docker-dropin.before" "$DROPIN"; else rm -f "$DROPIN"; fi
if [[ -f "$STATE/guard.before" ]]; then install -D -o root -g root -m 0755 "$STATE/guard.before" "$GUARD"; else rm -f "$GUARD"; fi
systemctl daemon-reload
rmdir "$SOURCE"
mv -- "$ROLLBACK" "$SOURCE"
chmod 0755 "$SOURCE"
systemctl start docker.service
docker ps --format 'CONTAINER={{.Names}} STATUS={{.Status}}'
df -hT / "$SSD"
echo "ROLLBACK_SOURCE=SD"
echo "RESULT=PASS"
