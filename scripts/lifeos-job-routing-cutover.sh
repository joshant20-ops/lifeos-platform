#!/usr/bin/env bash
set -Eeuo pipefail

# LifeOS job-routing cutover
#
# Purpose:
#   Stop the autonomous agent from publishing terminal job records into
#   lifeos-platform. Runtime state remains local in /var/lib/lifeos-agent.
#   Publication to lifeos-jobs is intentionally NOT enabled here until that
#   repository has verified write authentication.
#
# This script changes installed runtime state only. The canonical migration
# intent and deployment procedure live here in lifeos-platform.
#
# Safety:
#   - fail closed
#   - exact-match patch only
#   - timestamped backups
#   - no deletion of job state
#   - no change to lifeos-pi-control / execution publisher
#   - no Git commit/push from the Pi

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/job-routing-${STAMP}}"
PLATFORM_REPO="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
INSTALLED_AGENT="/usr/local/libexec/lifeos-autonomous-agent"
SERVICE="lifeos-autonomous-agent.service"
OVERRIDE_DIR="/etc/systemd/system/${SERVICE}.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/30-platform-readonly.conf"
LOG="${BACKUP_ROOT}/run.log"

say() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
gate() {
  local ans
  printf '\nGATE: %s\n' "$1"
  printf "Type EXACTLY 'YES' to continue: "
  read -r ans
  [[ "$ans" == "YES" ]] || die "Gate declined."
}

on_err() {
  local rc=$?
  printf '\nFAILED at line %s (exit %s).\n' "${BASH_LINENO[0]:-unknown}" "$rc" >&2
  [[ -d "${BACKUP_ROOT:-}" ]] && printf 'Recovery bundle: %s\n' "$BACKUP_ROOT" >&2
  exit "$rc"
}
trap on_err ERR

if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

mkdir -p "$BACKUP_ROOT"
touch "$LOG"
exec > >(tee -a "$LOG") 2>&1

say "LifeOS job-routing cutover"
info "Backup root: $BACKUP_ROOT"
info "Platform repo: $PLATFORM_REPO"

say "GATE 0 — Preflight"
[[ "$(hostname)" == "Docker" ]] || die "Expected host Docker."
[[ -d "$PLATFORM_REPO/.git" ]] || die "lifeos-platform checkout missing."
[[ -f "$INSTALLED_AGENT" ]] || die "Installed autonomous agent missing."
systemctl cat --no-pager "$SERVICE" >/dev/null || die "$SERVICE missing."

cd "$PLATFORM_REPO"

git fetch origin main >/dev/null
[[ "$(git branch --show-current)" == "main" ]] || die "lifeos-platform must be on main."

if [[ -n "$(git status --porcelain)" ]]; then
  git status --short
  die "lifeos-platform is dirty; refusing runtime cutover."
fi

LOCAL_HEAD="$(git rev-parse HEAD)"
ORIGIN_HEAD="$(git rev-parse origin/main)"
[[ "$LOCAL_HEAD" == "$ORIGIN_HEAD" ]] || die "lifeos-platform is not aligned with origin/main. Fetch/reset before running."

OLD_COUNT="$(grep -Fc 'job["record_publication"] = publish_record(PLATFORM_REPO, job)' "$INSTALLED_AGENT" || true)"
NEW_COUNT="$(grep -Fc '"state": "LOCAL_ONLY"' "$INSTALLED_AGENT" || true)"

info "Installed legacy publication calls: $OLD_COUNT"
info "Installed LOCAL_ONLY markers:       $NEW_COUNT"

if [[ "$OLD_COUNT" == "0" && "$NEW_COUNT" -ge 1 && -f "$OVERRIDE_FILE" ]]; then
  info "Cutover already appears applied; proceeding to validation only."
elif [[ "$OLD_COUNT" != "1" ]]; then
  die "Expected exactly one legacy publication call; found $OLD_COUNT."
fi

info "Platform status: clean and aligned with origin/main"
gate "Preflight passed. Create backup and disable direct platform job publication?"

say "GATE 1 — Backup"
cp -a "$INSTALLED_AGENT" "$BACKUP_ROOT/lifeos-autonomous-agent.before"
systemctl cat --no-pager "$SERVICE" > "$BACKUP_ROOT/lifeos-autonomous-agent.service.effective.before"
if [[ -f "$OVERRIDE_FILE" ]]; then
  cp -a "$OVERRIDE_FILE" "$BACKUP_ROOT/30-platform-readonly.conf.before"
fi
cp -a /var/lib/lifeos-agent "$BACKUP_ROOT/lifeos-agent-state.before" 2>/dev/null || true
sync
info "Backup complete."
gate "Backup complete. Apply exact runtime patch and platform read-only sandbox?"

say "GATE 2 — Runtime patch"
if grep -Fq 'job["record_publication"] = publish_record(PLATFORM_REPO, job)' "$INSTALLED_AGENT"; then
python3 - "$INSTALLED_AGENT" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '''    job["record_publication"] = publish_record(PLATFORM_REPO, job)\n    save(job)\n'''
new = '''    # Terminal job state remains local. Sanitised publication belongs to\n    # lifeos-jobs and is handled by the dedicated exporter, never by the\n    # authoritative lifeos-platform checkout.\n    job["record_publication"] = {\n        "state": "LOCAL_ONLY",\n        "reason": "lifeos-jobs publication handled separately",\n    }\n    save(job)\n'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"STOP: expected exactly one publication block, found {count}")
path.write_text(text.replace(old, new))
PY
fi

mkdir -p "$OVERRIDE_DIR"
cat > "$OVERRIDE_FILE" <<'EOF'
[Service]
# lifeos-platform is authoritative desired state and must never be mutated by
# runtime job completion. Keep only local mutable agent state writable.
ReadWritePaths=
ReadWritePaths=/var/lib/lifeos-agent
EOF

python3 -m py_compile "$INSTALLED_AGENT"
systemctl daemon-reload

info "Runtime patch compiled successfully."
info "Effective write paths:"
systemctl show "$SERVICE" -p ReadWritePaths --value

gate "Patch validates. Restart autonomous agent with lifeos-platform read-only?"

say "GATE 3 — Restart and health"
systemctl restart "$SERVICE"
sleep 3
[[ "$(systemctl is-active "$SERVICE")" == "active" ]] || {
  systemctl --no-pager --full status "$SERVICE" || true
  die "$SERVICE did not return active."
}

if journalctl -u "$SERVICE" --since '-3 minutes' --no-pager | grep -Eqi 'Traceback|PermissionError|ModuleNotFoundError|SyntaxError'; then
  journalctl -u "$SERVICE" --since '-3 minutes' --no-pager
  die "Recent autonomous-agent journal contains a fatal-looking Python/runtime error."
fi

info "$SERVICE is active."

say "GATE 4 — Invariants"
LEGACY_AFTER="$(grep -Fc 'job["record_publication"] = publish_record(PLATFORM_REPO, job)' "$INSTALLED_AGENT" || true)"
LOCAL_AFTER="$(grep -Fc '"state": "LOCAL_ONLY"' "$INSTALLED_AGENT" || true)"
[[ "$LEGACY_AFTER" == "0" ]] || die "Legacy platform publication call remains installed."
[[ "$LOCAL_AFTER" -ge 1 ]] || die "LOCAL_ONLY terminal-state marker missing."

WRITE_PATHS="$(systemctl show "$SERVICE" -p ReadWritePaths --value)"
[[ "$WRITE_PATHS" == *"/var/lib/lifeos-agent"* ]] || die "Agent state is not writable."
[[ "$WRITE_PATHS" != *"/home/joshan/lifeos-platform"* ]] || die "Platform checkout still writable by service."

if [[ -n "$(git -C "$PLATFORM_REPO" status --porcelain)" ]]; then
  git -C "$PLATFORM_REPO" status --short
  die "lifeos-platform became dirty during cutover."
fi

[[ "$(git -C "$PLATFORM_REPO" rev-parse HEAD)" == "$(git -C "$PLATFORM_REPO" rev-parse origin/main)" ]] || die "Platform branch diverged during cutover."

info "PASS: no direct job-record publication into lifeos-platform."
info "PASS: autonomous agent has no platform write path."
info "PASS: lifeos-platform remains clean and aligned."
info "PASS: local job state preserved."

cat <<EOF

RESULT=PASS
JOB_HISTORY_STATE=LOCAL_ONLY
PLATFORM_MUTATION=DISABLED
JOBS_REMOTE_PUBLICATION=NOT_YET_ENABLED
BACKUP=$BACKUP_ROOT

Next gate: verify/fix write authentication for /home/joshan/lifeos-jobs, then wire the existing sanitised exporter event-driven.
EOF
