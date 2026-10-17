#!/usr/bin/env bash
# Restore the retained SD tree for recovery while keeping persistent services
# blocked until /opt/stacks is safely re-established on the SSD.
set -Eeuo pipefail
SSD=/mnt/docker-data
SOURCE=/opt/stacks
ROLLBACK=/opt/stacks.sd-rollback-20261017
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
STATE=/var/lib/lifeos-storage-migration
FSTAB=/etc/fstab
DROPIN=/etc/systemd/system/docker.service.d/20-lifeos-storage.conf
GUARD=/usr/local/sbin/lifeos-require-opt-stacks-ssd
SSD_UNIT=$(systemd-escape --path --suffix=mount "$SSD")
STACKS_UNIT=$(systemd-escape --path --suffix=mount "$SOURCE")

[[ "$(findmnt -n -o UUID -T "$SSD" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || { echo "RESULT=FAIL"; echo "ERROR=ssd_uuid_mismatch"; exit 1; }
[[ -d "$STATE" && -d "$ROLLBACK" && ! -L "$ROLLBACK" ]] || { echo "RESULT=FAIL"; echo "ERROR=rollback_prerequisite_missing"; exit 1; }
[[ "$(findmnt -n -o UUID -T "$SOURCE" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || { echo "RESULT=FAIL"; echo "ERROR=opt_stacks_not_currently_ssd_bound"; exit 1; }

mapfile -t ids < <(docker ps -q)
if (("${#ids[@]}")); then docker stop --time 90 "${ids[@]}"; fi
systemctl stop docker.service
umount "$SOURCE"
rmdir "$SOURCE"
mv -- "$ROLLBACK" "$SOURCE"
chmod 0755 "$SOURCE"

python3 - "$FSTAB" "$SOURCE" <<'PY'
from pathlib import Path
import sys
path=Path(sys.argv[1]); target=sys.argv[2]
out=[]
skip_comment=False
for raw in path.read_text().splitlines():
    stripped=raw.strip()
    if stripped == '# LIFEOS-SSD-OPT-STACKS-BIND':
        skip_comment=True
        continue
    cols=stripped.split()
    if len(cols) >= 2 and cols[1] == target:
        skip_comment=False
        continue
    if skip_comment and not stripped:
        continue
    out.append(raw)
path.write_text('\n'.join(out)+'\n')
PY

cat >"$GUARD" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
TARGET=/opt/stacks
SSD=/mnt/docker-data
mountpoint -q "$TARGET"
[[ "$(findmnt -n -o TARGET -T "$TARGET")" == "$TARGET" ]]
[[ "$(findmnt -n -o UUID -T "$TARGET")" == "$EXPECTED_UUID" ]]
[[ "$(findmnt -n -o UUID -T "$SSD")" == "$EXPECTED_UUID" ]]
SH
chown root:root "$GUARD"
chmod 0755 "$GUARD"
install -d -o root -g root -m 0755 "$(dirname "$DROPIN")"
cat >"$DROPIN" <<EOF
[Unit]
RequiresMountsFor=$SSD
BindsTo=$SSD_UNIT $STACKS_UNIT
After=$SSD_UNIT $STACKS_UNIT

[Service]
ExecStartPre=$GUARD
EOF
chown root:root "$DROPIN"
chmod 0644 "$DROPIN"
systemctl daemon-reload
systemctl stop docker.service
echo "ROLLBACK_SOURCE=SD_RECOVERY_TREE"
echo "PERSISTENT_SERVICES=BLOCKED_FAIL_CLOSED"
echo "SSD_MOUNT_UUID=$(findmnt -n -o UUID -T "$SSD")"
df -hT / "$SSD"
echo "RESULT=PASS"
