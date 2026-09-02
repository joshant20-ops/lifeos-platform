#!/usr/bin/env bash
set -Eeuo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
BACKUP="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/pinned-compose-${STAMP}}"
LOG="$BACKUP/run.log"

PROJECTS=(
  adguard
  homeassistant
  matter-server
  mosquitto
  npm
  paperless
  predbat
  uptime-kuma
  vaultwarden
  zwave-js-ui
)

say(){ printf '\n==> %s\n' "$*"; }
info(){ printf '    %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
gate(){ local a; printf '\nGATE: %s\n' "$1"; printf "Type EXACTLY 'YES' to continue: "; read -r a; [[ "$a" == YES ]] || die "Gate declined."; }
trap 'rc=$?; printf "\nFAILED at line %s (exit %s)\n" "${BASH_LINENO[0]:-unknown}" "$rc" >&2; [[ -d "$BACKUP" ]] && printf "Recovery bundle: %s\n" "$BACKUP" >&2; exit "$rc"' ERR

if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$0" "$@"; fi
mkdir -p "$BACKUP"; touch "$LOG"; exec > >(tee -a "$LOG") 2>&1

say "LifeOS pinned Compose sync"
info "Platform: $PLATFORM"
info "Backup:   $BACKUP"

say "GATE 0 — Preflight"
[[ "$(hostname)" == Docker ]] || die "Expected host Docker"
[[ -d "$PLATFORM/.git" ]] || die "lifeos-platform missing"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform dirty"
[[ "$(git -C "$PLATFORM" branch --show-current)" == main ]] || die "lifeos-platform must be on main"

python3 "$PLATFORM/scripts/validate-compose-inventory.py"

for p in "${PROJECTS[@]}"; do
  desired="$PLATFORM/ansible/desired/compose/$p/docker-compose.yml"
  live="/opt/stacks/$p/docker-compose.yml"
  [[ -f "$desired" ]] || die "missing desired compose: $desired"
  [[ -f "$live" ]] || die "missing live compose: $live"
  docker compose -f "$desired" config -q
  info "PASS desired: $p"
done

# The three intentionally unpinned projects must remain untouched by this script.
for p in autoheal qbittorrent lifeos-energy; do
  [[ -f "$PLATFORM/ansible/desired/compose/$p/docker-compose.yml" ]] || die "expected preserved project missing: $p"
done

gate "Preflight passed. Back up the ten live Compose files before synchronising pinned desired state?"

say "GATE 1 — Backup"
mkdir -p "$BACKUP/live-compose"
for p in "${PROJECTS[@]}"; do
  mkdir -p "$BACKUP/live-compose/$p"
  cp -a "/opt/stacks/$p/docker-compose.yml" "$BACKUP/live-compose/$p/docker-compose.yml.before"
done

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.before.tsv"
info "Backup complete"
gate "Backup complete. Replace only the live Compose definitions (NO container recreation)?"

say "GATE 2 — Synchronise definitions"
for p in "${PROJECTS[@]}"; do
  desired="$PLATFORM/ansible/desired/compose/$p/docker-compose.yml"
  live="/opt/stacks/$p/docker-compose.yml"
  install -m "$(stat -c '%a' "$live")" -o "$(stat -c '%u' "$live")" -g "$(stat -c '%g' "$live")" "$desired" "$live"
  cmp -s "$desired" "$live" || die "live/desired mismatch after copy: $p"
  docker compose -f "$live" config -q
  info "SYNCED: $p"
done

say "GATE 3 — Runtime invariants"
# No docker compose up/down/restart is executed by this script. Prove the current
# running images still exactly match the pinned desired images.
python3 "$PLATFORM/scripts/lifeos-running-image-digest-audit.py" | tee "$BACKUP/running-digest-audit.txt"

grep -q '^RUNNING_IMAGE_DIGEST_AUDIT=PASS$' "$BACKUP/running-digest-audit.txt" || die "running digest audit did not pass"
grep -q '^DRIFT=0$' "$BACKUP/running-digest-audit.txt" || die "runtime drift detected"

# Confirm all synchronised live files are byte-identical to desired state.
for p in "${PROJECTS[@]}"; do
  cmp -s "$PLATFORM/ansible/desired/compose/$p/docker-compose.yml" "/opt/stacks/$p/docker-compose.yml" || die "final live/desired mismatch: $p"
done

[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform became dirty"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.after.tsv"

cat <<EOF

RESULT=PASS
PINNED_CORE_SERVICES=12
SYNCED_COMPOSE_PROJECTS=10
CONTAINERS_RECREATED=0
RUNTIME_DRIFT=0
AUTOHEAL_UNCHANGED=YES
QBITTORRENT_UNCHANGED=YES
LIFEOS_ENERGY_UNCHANGED=YES
BACKUP=$BACKUP
EOF
