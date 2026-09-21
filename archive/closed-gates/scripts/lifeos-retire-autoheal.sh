#!/usr/bin/env bash
set -Eeuo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
LIVE_DIR="/opt/stacks/autoheal"
LIVE_COMPOSE="$LIVE_DIR/docker-compose.yml"
BACKUP="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/autoheal-retire-${STAMP}}"
RETIRED="/opt/stacks-retired/${STAMP}/autoheal"

say(){ printf '\n==> %s\n' "$*"; }
info(){ printf '    %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
gate(){ local a; printf '\nGATE: %s\n' "$1"; printf "Type EXACTLY 'YES' to continue: "; read -r a; [[ "$a" == YES ]] || die "Gate declined."; }
trap 'rc=$?; printf "\nFAILED at line %s (exit %s)\n" "${BASH_LINENO[0]:-unknown}" "$rc" >&2; [[ -d "$BACKUP" ]] && printf "Recovery bundle: %s\n" "$BACKUP" >&2; exit "$rc"' ERR

if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$0" "$@"; fi
mkdir -p "$BACKUP"
exec > >(tee -a "$BACKUP/run.log") 2>&1

say "LifeOS Autoheal retirement"
info "Platform HEAD: $(git -C "$PLATFORM" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
info "Backup: $BACKUP"

say "GATE 0 — Preflight"
[[ "$(hostname)" == Docker ]] || die "Expected host Docker"
[[ -d "$PLATFORM/.git" ]] || die "lifeos-platform missing"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform dirty"
[[ -f "$LIVE_COMPOSE" ]] || die "Autoheal live Compose missing: $LIVE_COMPOSE"
docker inspect autoheal >/dev/null 2>&1 || die "Autoheal container missing"
[[ "$(docker inspect -f '{{.State.Running}}' autoheal)" == true ]] || die "Autoheal is not running"

restart_evidence="$(docker logs --since 720h autoheal 2>&1 | grep -Eic 'restart|restarting|healed|unhealthy.*restart' || true)"
info "Autoheal restart evidence (available <=30d logs): $restart_evidence"
[[ "$restart_evidence" == 0 ]] || die "Autoheal restart evidence is no longer zero; re-audit before removal"

mapfile -t protected < <(printf '%s\n' homeassistant mosquitto adguardhome vaultwarden matter-server zwave-js-ui predbat lifeos-energy nginx-proxy-manager uptime-kuma paperless-paperless-1 paperless-db-1 paperless-redis-1)
for c in "${protected[@]}"; do
  docker inspect "$c" >/dev/null 2>&1 || die "protected container missing: $c"
  [[ "$(docker inspect -f '{{.State.Running}}' "$c")" == true ]] || die "protected container not running: $c"
done
info "PASS: protected services running"

gate "Evidence shows no Autoheal interventions. Back up its stack before retirement?"

say "GATE 1 — Backup"
cp -a "$LIVE_DIR" "$BACKUP/autoheal-stack"
docker inspect autoheal > "$BACKUP/autoheal-inspect.json"
docker logs --since 720h autoheal > "$BACKUP/autoheal.log" 2>&1 || true
info "Backup complete"

gate "Backup complete. Stop/remove ONLY Autoheal without deleting volumes?"

say "GATE 2 — Retire Autoheal"
docker compose -f "$LIVE_COMPOSE" down
[[ -z "$(docker ps -aq -f name='^/autoheal$')" ]] || die "Autoheal container still exists"
mkdir -p "$(dirname "$RETIRED")"
mv "$LIVE_DIR" "$RETIRED"
info "Moved stack to $RETIRED"

say "GATE 3 — Survival check"
for c in "${protected[@]}"; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" == true ]] || die "protected container failed after Autoheal retirement: $c"
done

# Health-check containers that actually expose Docker health state.
for c in "${protected[@]}"; do
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$c" 2>/dev/null || true)"
  [[ "$health" != unhealthy ]] || die "protected container unhealthy after retirement: $c"
done

[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform became dirty"

cat <<EOF

RESULT=PASS
AUTOHEAL_RETIRED=YES
AUTOHEAL_RESTART_EVIDENCE=$restart_evidence
PROTECTED_SERVICES_SURVIVED=YES
DOCKER_VOLUMES_DELETED=NO
DESIRED_STATE_REMOVAL=NEXT_GATE
RETIRED_PATH=$RETIRED
BACKUP=$BACKUP
EOF
