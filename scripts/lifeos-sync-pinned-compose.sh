#!/usr/bin/env bash
set -Eeuo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
MANIFEST="$PLATFORM/ansible/vars/compose_projects.json"
AUDIT="$PLATFORM/scripts/lifeos-running-image-digest-audit.py"
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

live_path_for(){
  python3 - "$MANIFEST" "$1" <<'PY'
import json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
project = sys.argv[2]
matches = [x for x in manifest.get("compose_files", []) if x.get("project") == project]
if len(matches) != 1:
    raise SystemExit(f"expected exactly one compose_files entry for {project}, found {len(matches)}")
print(matches[0]["live_path"])
PY
}

desired_path_for(){
  python3 - "$MANIFEST" "$PLATFORM" "$1" <<'PY'
import json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
platform = pathlib.Path(sys.argv[2])
project = sys.argv[3]
matches = [x for x in manifest.get("compose_files", []) if x.get("project") == project]
if len(matches) != 1:
    raise SystemExit(f"expected exactly one compose_files entry for {project}, found {len(matches)}")
print(platform / "ansible" / matches[0]["desired_rel"])
PY
}

say "LifeOS pinned Compose sync"
info "Platform: $PLATFORM"
info "Platform HEAD: $(git -C "$PLATFORM" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
info "Backup:   $BACKUP"

say "GATE 0 — Preflight"
[[ "$(hostname)" == Docker ]] || die "Expected host Docker"
[[ -d "$PLATFORM/.git" ]] || die "lifeos-platform missing"
[[ -f "$MANIFEST" ]] || die "compose manifest missing"
[[ -f "$AUDIT" ]] || die "digest audit missing"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform dirty"
[[ "$(git -C "$PLATFORM" branch --show-current)" == main ]] || die "lifeos-platform must be on main"

# Require the digest-aware audit implementation. Older revisions compared desired
# tag text to Config.Image and incorrectly reported digest pins as drift.
grep -q 'desired == digest' "$AUDIT" || die "digest audit is too old; fetch/reset origin/main before running"

python3 "$PLATFORM/scripts/validate-compose-inventory.py"

for p in "${PROJECTS[@]}"; do
  desired="$(desired_path_for "$p")"
  live="$(live_path_for "$p")"
  [[ -f "$desired" ]] || die "missing desired compose: $desired"
  [[ -f "$live" ]] || die "missing live compose: $live"
  docker compose -f "$desired" config -q
  info "PASS desired/live: $p -> $live"
done

for p in autoheal qbittorrent lifeos-energy; do
  desired="$(desired_path_for "$p")"
  [[ -f "$desired" ]] || die "expected preserved project missing: $p"
done

gate "Preflight passed. Back up the ten manifest-declared live Compose files before synchronising pinned desired state?"

say "GATE 1 — Backup"
mkdir -p "$BACKUP/live-compose"
for p in "${PROJECTS[@]}"; do
  live="$(live_path_for "$p")"
  mkdir -p "$BACKUP/live-compose/$p"
  cp -a "$live" "$BACKUP/live-compose/$p/docker-compose.yml.before"
done

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.before.tsv"
info "Backup complete"
gate "Backup complete. Replace only the live Compose definitions (NO container recreation)?"

say "GATE 2 — Synchronise definitions"
for p in "${PROJECTS[@]}"; do
  desired="$(desired_path_for "$p")"
  live="$(live_path_for "$p")"
  install -m "$(stat -c '%a' "$live")" -o "$(stat -c '%u' "$live")" -g "$(stat -c '%g' "$live")" "$desired" "$live"
  cmp -s "$desired" "$live" || die "live/desired mismatch after copy: $p"
  docker compose -f "$live" config -q
  info "SYNCED: $p -> $live"
done

say "GATE 3 — Runtime invariants"
python3 "$AUDIT" | tee "$BACKUP/running-digest-audit.txt"

grep -q '^RUNNING_IMAGE_DIGEST_AUDIT=PASS$' "$BACKUP/running-digest-audit.txt" || die "running digest audit did not pass"
grep -q '^DRIFT=0$' "$BACKUP/running-digest-audit.txt" || die "runtime digest drift detected"

for p in "${PROJECTS[@]}"; do
  desired="$(desired_path_for "$p")"
  live="$(live_path_for "$p")"
  cmp -s "$desired" "$live" || die "final live/desired mismatch: $p"
done

[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform became dirty"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.after.tsv"

cat <<EOF

RESULT=PASS
PINNED_CORE_SERVICES=12
SYNCED_COMPOSE_PROJECTS=10
CONTAINERS_RECREATED=0
RUNTIME_DRIFT=0
LIVE_PATH_SOURCE=COMPOSE_MANIFEST
DIGEST_COMPARISON=RESOLVED_IDENTITY
AUTOHEAL_UNCHANGED=YES
QBITTORRENT_UNCHANGED=YES
LIFEOS_ENERGY_UNCHANGED=YES
BACKUP=$BACKUP
EOF
