#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
DESIRED="$PLATFORM/ansible/desired/compose/lifeos-engineer-ui/docker-compose.yml"
LIVE_DIR=/opt/stacks/lifeos-engineer-ui
LIVE="$LIVE_DIR/docker-compose.yml"
ENV_DIR=/etc/lifeos
ENV_FILE="$ENV_DIR/openwebui.env"
SECRET_FILE=/var/lib/lifeos-openwebui/webui-secret
CONTAINER=lifeos-engineer-ui
VOLUME=lifeos-engineer-openwebui
BACKUP="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/engineer-ui-adopt-$(date +%Y%m%d-%H%M%S)}"

say(){ printf '\n==> %s\n' "$*"; }
info(){ printf '    %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
gate(){ local a; printf '\nGATE: %s\n' "$1"; printf "Type EXACTLY 'YES' to continue: "; read -r a; [[ "$a" == YES ]] || die "Gate declined."; }
trap 'rc=$?; printf "\nFAILED at line %s (exit %s)\n" "${BASH_LINENO[0]:-unknown}" "$rc" >&2; [[ -d "$BACKUP" ]] && printf "Recovery bundle: %s\n" "$BACKUP" >&2; exit "$rc"' ERR

if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$0" "$@"; fi
mkdir -p "$BACKUP"
exec > >(tee -a "$BACKUP/run.log") 2>&1

say "LifeOS Engineer UI adoption"
info "Platform HEAD: $(git -C "$PLATFORM" rev-parse --short=12 HEAD)"
info "Backup: $BACKUP"

say "GATE 0 — Preflight"
[[ "$(hostname)" == Docker ]] || die "Expected host Docker"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform dirty"
[[ -f "$DESIRED" ]] || die "desired Open WebUI compose missing"
[[ -s "$SECRET_FILE" ]] || die "existing Open WebUI secret missing"
docker volume inspect "$VOLUME" >/dev/null 2>&1 || die "existing Open WebUI data volume missing"
docker inspect "$CONTAINER" >/dev/null 2>&1 || die "existing Open WebUI container missing"
[[ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER")" == running ]] || die "existing Open WebUI not running"
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER")" == healthy ]] || die "existing Open WebUI not healthy"
curl -fsS --max-time 5 http://127.0.0.1:8793/health >/dev/null || die "LifeOS Engineer backend unhealthy"
curl -fsS --max-time 5 http://127.0.0.1:8792/health >/dev/null || die "Open WebUI endpoint unhealthy"
python3 "$PLATFORM/scripts/validate-compose-inventory.py"
info "PASS: existing UI healthy and persistent data present"

gate "Preflight passed. Back up current container metadata and create root-owned Compose runtime files?"

say "GATE 1 — Backup and runtime files"
docker inspect "$CONTAINER" > "$BACKUP/container.before.json"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > "$BACKUP/docker-ps.before.tsv"
cp -a "$SECRET_FILE" "$BACKUP/webui-secret.before"
install -d -o root -g root -m 0755 "$ENV_DIR" "$LIVE_DIR"
{
  umask 077
  printf 'WEBUI_SECRET_KEY=%s\n' "$(cat "$SECRET_FILE")" > "$ENV_FILE"
}
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"
install -o root -g root -m 0644 "$DESIRED" "$LIVE"
docker compose -f "$LIVE" config -q
info "PASS: Compose config validates"

gate "Runtime files validate. Replace the ad-hoc container with the Compose-managed equivalent using the existing data volume?"

say "GATE 2 — Compose adoption"
docker rm -f "$CONTAINER" >/dev/null
docker compose -f "$LIVE" up -d --no-build

say "GATE 3 — Health and ownership"
for _ in $(seq 1 60); do
  if [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || true)" == healthy ]] && \
     curl -fsS --max-time 5 http://127.0.0.1:8792/health >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
[[ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER")" == running ]] || die "Open WebUI not running after adoption"
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER")" == healthy ]] || die "Open WebUI not healthy after adoption"
[[ "$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$CONTAINER")" == lifeos-engineer-ui ]] || die "Open WebUI is not Compose-managed"
[[ "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/backend/data"}}{{.Name}}{{end}}{{end}}' "$CONTAINER")" == "$VOLUME" ]] || die "Open WebUI persistent volume changed"
curl -fsS --max-time 5 http://127.0.0.1:8793/health >/dev/null || die "Engineer backend unhealthy after adoption"
curl -fsS --max-time 5 http://127.0.0.1:8792/health >/dev/null || die "Open WebUI endpoint unhealthy after adoption"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform became dirty"

cat <<EOF

RESULT=PASS
ENGINEER_UI_ADOPTED=YES
COMPOSE_PROJECT=lifeos-engineer-ui
IMAGE=ghcr.io/open-webui/open-webui:v0.11.1
PERSISTENT_VOLUME=$VOLUME
BACKEND_HEALTH=PASS
UI_HEALTH=PASS
PLATFORM_DIRTY=NO
BACKUP=$BACKUP
EOF
