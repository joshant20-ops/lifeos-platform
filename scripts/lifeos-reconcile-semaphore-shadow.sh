#!/usr/bin/env bash
set -Eeuo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
GIT_USER=joshan
LIVE_DIR=/opt/stacks/lifeos-semaphore-shadow
LIVE_COMPOSE="$LIVE_DIR/docker-compose.yml"
CANONICAL="$PLATFORM/orchestration/semaphore/docker-compose.yml"
LAUNCHER="$PLATFORM/governor/runtime_jobs/c3751aaff97b.sh"
BACKUP="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/semaphore-reconcile-$STAMP}"
PROJECT=lifeos-semaphore-shadow
ENV_FILE=/etc/lifeos/semaphore.env
DEFAULT_SECRETS_DIR=/etc/lifeos/semaphore-secrets

say(){ printf '\n==> %s\n' "$*"; }
info(){ printf '    %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
trap 'rc=$?; printf "\nFAILED at line %s (exit %s)\n" "${BASH_LINENO[0]:-unknown}" "$rc" >&2; [[ -d "$BACKUP" ]] && printf "Recovery bundle: %s\n" "$BACKUP" >&2; exit "$rc"' ERR

if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$0" "$@"; fi
mkdir -p "$BACKUP"
exec > >(tee -a "$BACKUP/run.log") 2>&1

git_as_user() {
  runuser -u "$GIT_USER" -- env -i HOME=/home/joshan PATH=/usr/bin:/bin LANG=C.UTF-8 git -C "$PLATFORM" "$@"
}

private_lan_ip() {
  local candidate
  candidate=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}')
  [[ "$candidate" =~ ^10\. || "$candidate" =~ ^192\.168\. || "$candidate" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. ]] || return 1
  printf '%s\n' "$candidate"
}

say "LifeOS Semaphore shadow reconciliation"
info "Platform HEAD: $(git_as_user rev-parse --short=12 HEAD)"
info "Git metadata user: $GIT_USER"
info "Backup: $BACKUP"

say "STAGE 0 — Preflight"
[[ "$(hostname)" == Docker ]] || die "expected host Docker"
[[ -d "$PLATFORM/.git" ]] || die "platform checkout missing"
[[ -f "$CANONICAL" ]] || die "canonical Semaphore compose missing"
[[ -f "$LAUNCHER" ]] || die "published Semaphore launcher missing"
[[ "$(stat -c '%U:%G' "$PLATFORM/.git/index")" == "$GIT_USER:$GIT_USER" ]] || die "git index ownership is not $GIT_USER:$GIT_USER"
[[ -z "$(git_as_user status --porcelain)" ]] || die "lifeos-platform dirty"
[[ "$(git_as_user branch --show-current)" == main ]] || die "lifeos-platform must be on main"
git_as_user ls-files --error-unmatch orchestration/semaphore/docker-compose.yml governor/runtime_jobs/c3751aaff97b.sh >/dev/null

existing_sem="$(docker ps --format '{{.Names}}' | grep '^lifeos-semaphore-shadow-semaphore-1$' || true)"
if [[ -n "$existing_sem" ]]; then
  old_dialect="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' lifeos-semaphore-shadow-semaphore-1 | awk -F= '$1=="SEMAPHORE_DB_DIALECT"{print $2;exit}')"
  [[ "$old_dialect" == sqlite ]] || die "expected existing shadow to be sqlite, got ${old_dialect:-unknown}"
  info "Existing shadow dialect: sqlite"
else
  old_dialect=sqlite
  info "Legacy SQLite container already stopped by previous safe attempt"
fi

say "STAGE 1 — Recovery backup"
mkdir -p "$BACKUP/live-stack" "$BACKUP/inspect"
[[ -f "$LIVE_COMPOSE" ]] && cp -a "$LIVE_COMPOSE" "$BACKUP/live-stack/docker-compose.yml.before"
cp -a "$ENV_FILE" "$BACKUP/semaphore.env.before" 2>/dev/null || true
cp -a "$DEFAULT_SECRETS_DIR" "$BACKUP/semaphore-secrets.before" 2>/dev/null || true

if [[ -n "$existing_sem" ]]; then
  docker inspect lifeos-semaphore-shadow-semaphore-1 > "$BACKUP/inspect/semaphore.before.json"
  docker logs --timestamps lifeos-semaphore-shadow-semaphore-1 > "$BACKUP/inspect/semaphore.before.log" 2>&1 || true
fi

for vol in lifeos-semaphore-shadow_semaphore_data lifeos-semaphore-shadow_semaphore_config; do
  if docker volume inspect "$vol" >/dev/null 2>&1; then
    mp="$(docker volume inspect -f '{{.Mountpoint}}' "$vol")"
    tar -C "$mp" -czf "$BACKUP/${vol}.tgz" .
    info "Backed up volume: $vol"
  fi
done

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.before.tsv"

say "STAGE 2 — Normalize canonical Semaphore bootstrap state"
install -d -o root -g root -m 0755 /etc/lifeos
bind_ip=""
secrets_dir=""
if [[ -f "$ENV_FILE" ]]; then
  [[ ! -L "$ENV_FILE" ]] || die "Semaphore env file must not be a symlink"
  [[ "$(stat -c '%U:%G:%a' "$ENV_FILE")" == root:root:600 ]] || die "unsafe Semaphore env permissions"
  bind_ip="$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE")"
  secrets_dir="$(awk -F= '$1=="LIFEOS_SEMAPHORE_SECRETS_DIR"{print $2;exit}' "$ENV_FILE")"
fi
if [[ -z "$bind_ip" ]]; then
  bind_ip="$(private_lan_ip)" || die "private LAN IP could not be derived"
  info "Derived canonical Semaphore bind IP: $bind_ip"
fi
[[ "$bind_ip" != 0.0.0.0 && "$bind_ip" != 127.* ]] || die "unsafe derived Semaphore bind IP: $bind_ip"
if [[ "$secrets_dir" != "$DEFAULT_SECRETS_DIR" || ! -e "$DEFAULT_SECRETS_DIR" ]]; then
  [[ -z "$secrets_dir" || "$secrets_dir" == "$DEFAULT_SECRETS_DIR" || ! -e "$secrets_dir" ]] || die "refusing to replace an existing noncanonical secrets directory: $secrets_dir"
  info "Normalizing Semaphore env/secrets to canonical path: $DEFAULT_SECRETS_DIR"
  umask 077
  printf 'LIFEOS_SEMAPHORE_BIND_IP=%s\nLIFEOS_SEMAPHORE_SECRETS_DIR=%s\n' "$bind_ip" "$DEFAULT_SECRETS_DIR" > "$ENV_FILE"
  chown root:root "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

say "STAGE 3 — Stop legacy SQLite shadow if still present"
if [[ -n "$existing_sem" ]]; then
  if [[ -f "$LIVE_COMPOSE" ]]; then
    docker compose -p "$PROJECT" -f "$LIVE_COMPOSE" down || die "failed to stop legacy Semaphore shadow"
  else
    docker rm -f lifeos-semaphore-shadow-semaphore-1 >/dev/null
  fi
fi
[[ -z "$(docker ps -a --format '{{.Names}}' | grep '^lifeos-semaphore-shadow-' || true)" ]] || die "legacy shadow containers remain"

say "STAGE 4 — Deploy canonical PostgreSQL shadow"
LIFEOS_REPO_ROOT="$PLATFORM" bash "$LAUNCHER" | tee "$BACKUP/canonical-launcher.out"
grep -q '^SEMAPHORE_SHADOW=PASS ' "$BACKUP/canonical-launcher.out" || die "canonical launcher did not report PASS"
grep -q '^RESULT=PASS$' "$BACKUP/canonical-launcher.out" || die "canonical launcher result was not PASS"

say "STAGE 5 — Runtime invariants"
mapfile -t cids < <(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.ID}}')
(( ${#cids[@]} == 2 )) || die "expected two running canonical shadow containers, found ${#cids[@]}"

for svc in semaphore-db semaphore; do
  cid="$(docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$CANONICAL" ps -q "$svc")"
  [[ -n "$cid" ]] || die "missing canonical service: $svc"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  [[ "$health" == healthy ]] || die "$svc health=$health"
done

sem_cid="$(docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$CANONICAL" ps -q semaphore)"
new_dialect="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$sem_cid" | awk -F= '$1=="SEMAPHORE_DB_DIALECT"{print $2;exit}')"
[[ "$new_dialect" == postgres ]] || die "Semaphore did not switch to postgres"

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.after.tsv"

for unit in lifeos-autonomous-agent.service lifeos-engineer.service lifeos-control-job-submit.socket lifeos-root-broker.socket; do
  systemctl is-active --quiet "$unit" || die "protected execution unit not active: $unit"
done

[[ -z "$(git_as_user status --porcelain)" ]] || die "lifeos-platform became dirty"
[[ "$(stat -c '%U:%G' "$PLATFORM/.git/index")" == "$GIT_USER:$GIT_USER" ]] || die "git metadata ownership changed"

cat <<EOF

RESULT=PASS
SEMAPHORE_SHADOW_RECONCILED=YES
OLD_DB_DIALECT=sqlite
NEW_DB_DIALECT=postgres
CANONICAL_SERVICES=2
CUSTOM_EXECUTION_PATH_CHANGED=NO
OLD_SQLITE_VOLUMES_DELETED=NO
GIT_METADATA_OWNER_PRESERVED=YES
BACKUP=$BACKUP
NEXT_ACTION=audit_replacement_scope_before_disabling_custom_orchestration
EOF
