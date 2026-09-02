#!/usr/bin/env bash
set -Eeuo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
JOBS="${LIFEOS_JOBS_REPO:-/home/joshan/lifeos-jobs}"
STATE="${LIFEOS_AGENT_STATE:-/var/lib/lifeos-agent}"
EXPORTER="$PLATFORM/governor/scripts/export-lifeos-job-records.sh"
UNIT="/etc/systemd/system/lifeos-jobs-export.service"
PATH_UNIT="/etc/systemd/system/lifeos-jobs-export.path"
BACKUP="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/jobs-exporter-$STAMP}"
LOG="$BACKUP/run.log"

say(){ printf '\n==> %s\n' "$*"; }
info(){ printf '    %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
gate(){ local a; printf '\nGATE: %s\n' "$1"; printf "Type EXACTLY 'YES' to continue: "; read -r a; [[ "$a" == YES ]] || die "Gate declined."; }
trap 'rc=$?; printf "\nFAILED at line %s (exit %s)\n" "${BASH_LINENO[0]:-unknown}" "$rc" >&2; [[ -d "$BACKUP" ]] && printf "Recovery bundle: %s\n" "$BACKUP" >&2; exit "$rc"' ERR

if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$0" "$@"; fi
mkdir -p "$BACKUP"; touch "$LOG"; exec > >(tee -a "$LOG") 2>&1

say "LifeOS jobs exporter cutover"
info "Platform: $PLATFORM"
info "Jobs repo: $JOBS"
info "State:     $STATE"
info "Backup:    $BACKUP"

say "GATE 0 — Preflight"
[[ "$(hostname)" == Docker ]] || die "Expected host Docker"
[[ -d "$PLATFORM/.git" ]] || die "lifeos-platform missing"
[[ -d "$JOBS/.git" ]] || die "lifeos-jobs missing"
[[ -d "$STATE" ]] || die "agent state missing"
[[ -x "$EXPORTER" || -f "$EXPORTER" ]] || die "exporter missing"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform dirty"
[[ -z "$(git -C "$JOBS" status --porcelain)" ]] || die "lifeos-jobs dirty"

git -C "$JOBS" fetch origin main >/dev/null
[[ "$(git -C "$JOBS" rev-parse HEAD)" == "$(git -C "$JOBS" rev-parse origin/main)" ]] || die "lifeos-jobs not aligned with origin/main"

git -C "$JOBS" push --dry-run origin HEAD:main >/dev/null
info "PASS: lifeos-jobs write auth works"

# Platform must already be protected from direct runtime mutation.
WRITE_PATHS="$(systemctl show lifeos-autonomous-agent.service -p ReadWritePaths --value)"
[[ "$WRITE_PATHS" == *"/var/lib/lifeos-agent"* ]] || die "agent state write path missing"
[[ "$WRITE_PATHS" != *"/home/joshan/lifeos-platform"* ]] || die "platform still writable by autonomous agent"

gate "Preflight passed. Back up current exporter/systemd state?"

say "GATE 1 — Backup"
cp -a "$EXPORTER" "$BACKUP/export-lifeos-job-records.sh.before"
[[ -f "$UNIT" ]] && cp -a "$UNIT" "$BACKUP/lifeos-jobs-export.service.before"
[[ -f "$PATH_UNIT" ]] && cp -a "$PATH_UNIT" "$BACKUP/lifeos-jobs-export.path.before"
git -C "$JOBS" status --short --branch > "$BACKUP/lifeos-jobs-status.before"
git -C "$PLATFORM" status --short --branch > "$BACKUP/lifeos-platform-status.before"
info "Backup complete"
gate "Install event-driven exporter units?"

say "GATE 2 — Install event-driven export"
install -m 0755 "$EXPORTER" /usr/local/sbin/export-lifeos-job-records

cat > "$UNIT" <<'EOF'
[Unit]
Description=Export sanitised LifeOS job records to lifeos-jobs
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=joshan
Group=joshan
Environment=HOME=/home/joshan
Environment=LIFEOS_AGENT_STATE=/var/lib/lifeos-agent
Environment=LIFEOS_JOBS_REPO=/home/joshan/lifeos-jobs
ExecStart=/usr/local/sbin/export-lifeos-job-records
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/home/joshan/lifeos-jobs
ReadOnlyPaths=/var/lib/lifeos-agent
TimeoutStartSec=3min
EOF

cat > "$PATH_UNIT" <<'EOF'
[Unit]
Description=Watch LifeOS agent state for completed-job export

[Path]
PathChanged=/var/lib/lifeos-agent
Unit=lifeos-jobs-export.service
MakeDirectory=false

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemd-analyze verify "$UNIT" "$PATH_UNIT" >/dev/null
info "Systemd units validate"
gate "Units validate. Run one manual export before enabling the path watcher?"

say "GATE 3 — Manual export test"
# Preserve exact baseline for later invariant checks.
PLATFORM_HEAD="$(git -C "$PLATFORM" rev-parse HEAD)"
PLATFORM_STATUS_BEFORE="$(git -C "$PLATFORM" status --porcelain)"
JOBS_HEAD_BEFORE="$(git -C "$JOBS" rev-parse HEAD)"

systemctl start lifeos-jobs-export.service
[[ "$(systemctl show lifeos-jobs-export.service -p Result --value)" == success ]] || {
  journalctl -u lifeos-jobs-export.service --since '-5 min' --no-pager
  die "manual exporter service failed"
}

[[ "$(git -C "$PLATFORM" rev-parse HEAD)" == "$PLATFORM_HEAD" ]] || die "platform HEAD changed"
[[ "$(git -C "$PLATFORM" status --porcelain)" == "$PLATFORM_STATUS_BEFORE" ]] || die "platform working tree changed"
[[ -z "$(git -C "$JOBS" status --porcelain)" ]] || { git -C "$JOBS" status --short; die "lifeos-jobs left dirty after export"; }

git -C "$JOBS" fetch origin main >/dev/null
[[ "$(git -C "$JOBS" rev-parse HEAD)" == "$(git -C "$JOBS" rev-parse origin/main)" ]] || die "local lifeos-jobs not aligned after export"
JOBS_HEAD_AFTER="$(git -C "$JOBS" rev-parse HEAD)"
info "Jobs HEAD before: $JOBS_HEAD_BEFORE"
info "Jobs HEAD after:  $JOBS_HEAD_AFTER"
info "PASS: manual export completed and platform stayed untouched"

gate "Manual export passed. Enable event-driven path watcher?"

say "GATE 4 — Enable path watcher"
systemctl enable --now lifeos-jobs-export.path
[[ "$(systemctl is-active lifeos-jobs-export.path)" == active ]] || die "path watcher not active"
[[ "$(systemctl is-enabled lifeos-jobs-export.path)" == enabled ]] || die "path watcher not enabled"

# Give path unit a moment to settle, then verify no failure loop.
sleep 2
if systemctl --failed --no-legend | grep -q 'lifeos-jobs-export'; then
  systemctl --no-pager --full status lifeos-jobs-export.path lifeos-jobs-export.service || true
  die "jobs exporter has failed unit state"
fi

say "GATE 5 — Final invariants"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform dirty"
[[ -z "$(git -C "$JOBS" status --porcelain)" ]] || die "lifeos-jobs dirty"
[[ "$(systemctl is-active lifeos-autonomous-agent.service)" == active ]] || die "autonomous agent inactive"
[[ "$(systemctl is-active lifeos-jobs-export.path)" == active ]] || die "export path inactive"

cat <<EOF

RESULT=PASS
JOB_HISTORY_STATE=EXPORTED_TO_LIFEOS_JOBS
PLATFORM_MUTATION=DISABLED
JOBS_REMOTE_PUBLICATION=ENABLED
EXPORT_TRIGGER=SYSTEMD_PATH
JOBS_HEAD=$JOBS_HEAD_AFTER
BACKUP=$BACKUP
EOF
