#!/usr/bin/env bash
set -euo pipefail

# ---- Settings ----
DEST_DIR="/mnt/synology-backups"
HOST="$(hostname -s)"
DATE="$(date -u +'%Y-%m-%d_%H-%M-%S_GMT')"
OUT="${DEST_DIR}/${HOST}_sd_${DATE}.img.gz"
LOG="${DEST_DIR}/${HOST}_sd_backup.log"
KEEP=4   # keep newest N images

# ---- Helpers ----
log() { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }

# ---- Safety checks ----
if ! mountpoint -q "$DEST_DIR"; then
  log "ERROR: $DEST_DIR is not mounted. Aborting."
  exit 1
fi

SD_DEV="/dev/mmcblk0"
if [[ ! -b "$SD_DEV" ]]; then
  log "ERROR: $SD_DEV not found (expected SD card block device). Aborting."
  exit 1
fi

# Don't run if destination is too full (needs headroom)
AVAIL_KB="$(df -Pk "$DEST_DIR" | awk 'NR==2{print $4}')"
if [[ "$AVAIL_KB" -lt 3000000 ]]; then
  log "ERROR: Not enough free space on NAS (<~3GB). Aborting."
  exit 1
fi

log "Starting SD image backup from $SD_DEV to $OUT"

# Try to reduce churn (best-effort; harmless if it fails)
sync

# Create compressed image
# pv is optional; if missing, fallback without it.
if command -v pv >/dev/null 2>&1; then
  SIZE_BYTES="$(blockdev --getsize64 "$SD_DEV")"
  log "Device size: $SIZE_BYTES bytes"
  pv -s "$SIZE_BYTES" "$SD_DEV" | gzip -1 > "$OUT"
else
  dd if="$SD_DEV" bs=4M status=progress | gzip -1 > "$OUT"
fi

sync
log "Backup complete: $(ls -lh "$OUT" | awk '{print $5}') -> $OUT"

# Retention: keep newest $KEEP images for this host
log "Applying retention: keep newest $KEEP images"
ls -1t "${DEST_DIR}/${HOST}_sd_"*.img.gz 2>/dev/null | tail -n +"$((KEEP+1))" | xargs -r rm -f

log "Done."
