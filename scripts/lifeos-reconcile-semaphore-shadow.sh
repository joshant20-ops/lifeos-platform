#!/usr/bin/env bash
set -Eeuo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
LIVE_DIR=/opt/stacks/lifeos-semaphore-shadow
LIVE_COMPOSE="$LIVE_DIR/docker-compose.yml"
CANONICAL="$PLATFORM/orchestration/semaphore/docker-compose.yml"
LAUNCHER="$PLATFORM/governor/runtime_jobs/c3751aaff97b.sh"
BACKUP="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/semaphore-reconcile-$STAMP}"
PROJECT=lifeos-semaphore-shadow

say(){ printf '\n==> %s\n' "$*"; }
info(){ printf '    %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
trap 'rc=$?; printf "\nFAILED at line %s (exit %s)\n" "${BASH_LINENO[0]:-unknown}" "$rc" >&2; [[ -d "$BACKUP" ]] && printf "Recovery bundle: %s\n" "$BACKUP" >&2; exit "$rc"' ERR

if [[ $EUID -ne 0 ]]; then exec sudo -E bash "$0" "$@"; fi
mkdir -p "$BACKUP"
exec > >(tee -a "$BACKUP/run.log") 2>&1

say "LifeOS Semaphore shadow reconciliation"
info "Platform HEAD: $(git -C "$PLATFORM" rev-parse --short=12 HEAD)"
info "Backup: $BACKUP"

say "STAGE 0 — Preflight"
[[ "$(hostname)" == Docker ]] || die "expected host Docker"
[[ -d "$PLATFORM/.git" ]] || die "platform checkout missing"
[[ -f "$CANONICAL" ]] || die "canonical Semaphore compose missing"
[[ -f "$LAUNCHER" ]] || die "published Semaphore launcher missing"
[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform dirty"
[[ "$(git -C "$PLATFORM" branch --show-current)" == main ]] || die "lifeos-platform must be on main"
git -C "$PLATFORM" ls-files --error-unmatch orchestration/semaphore/docker-compose.yml governor/runtime_jobs/c3751aaff97b.sh >/dev/null

docker ps --format '{{.Names}}' | grep -qx lifeos-semaphore-shadow-semaphore-1 || die "existing Semaphore shadow container not running"
old_dialect="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' lifeos-semaphore-shadow-semaphore-1 | awk -F= '$1=="SEMAPHORE_DB_DIALECT"{print $2;exit}')"
[[ "$old_dialect" == sqlite ]] || die "expected existing shadow to be sqlite, got ${old_dialect:-unknown}"
info "Existing shadow dialect: sqlite"

say "STAGE 1 — Recovery backup"
mkdir -p "$BACKUP/live-stack" "$BACKUP/inspect"
[[ -f "$LIVE_COMPOSE" ]] && cp -a "$LIVE_COMPOSE" "$BACKUP/live-stack/docker-compose.yml.before"
cp -a /etc/lifeos/semaphore.env "$BACKUP/semaphore.env.before" 2>/dev/null || true
cp -a /etc/lifeos/semaphore-secrets "$BACKUP/semaphore-secrets.before" 2>/dev/null || true

docker inspect lifeos-semaphore-shadow-semaphore-1 > "$BACKUP/inspect/semaphore.before.json"
docker logs --timestamps lifeos-semaphore-shadow-semaphore-1 > "$BACKUP/inspect/semaphore.before.log" 2>&1 || true

# Archive the mounted SQLite/config data without deleting or mutating the volume.
for vol in lifeos-semaphore-shadow_semaphore_data lifeos-semaphore-shadow_semaphore_config; do
  if docker volume inspect "$vol" >/dev/null 2>&1; then
    mp="$(docker volume inspect -f '{{.Mountpoint}}' "$vol")"
    tar -C "$mp" -czf "$BACKUP/${vol}.tgz" .
    info "Backed up volume: $vol"
  fi
done

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.before.tsv"

say "STAGE 2 — Stop legacy SQLite shadow"
if [[ -f "$LIVE_COMPOSE" ]]; then
  docker compose -p "$PROJECT" -f "$LIVE_COMPOSE" down || die "failed to stop legacy Semaphore shadow"
else
  docker rm -f lifeos-semaphore-shadow-semaphore-1 >/dev/null
fi
# Deliberately do not pass -v: old SQLite/config volumes remain available for rollback.
[[ -z "$(docker ps -a --format '{{.Names}}' | grep '^lifeos-semaphore-shadow-' || true)" ]] || die "legacy shadow containers remain"

say "STAGE 3 — Deploy canonical PostgreSQL shadow"
# Reuse the already-reviewed root launcher. It creates root-owned env/secrets if
# needed, validates published source, pulls native arm64 images, launches the
# canonical Compose contract, and verifies health/privilege boundaries.
LIFEOS_REPO_ROOT="$PLATFORM" bash "$LAUNCHER" | tee "$BACKUP/canonical-launcher.out"
grep -q '^SEMAPHORE_SHADOW=PASS ' "$BACKUP/canonical-launcher.out" || die "canonical launcher did not report PASS"
grep -q '^RESULT=PASS$' "$BACKUP/canonical-launcher.out" || die "canonical launcher result was not PASS"

say "STAGE 4 — Runtime invariants"
mapfile -t cids < <(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.ID}}')
(( ${#cids[@]} == 2 )) || die "expected two running canonical shadow containers, found ${#cids[@]}"

for svc in semaphore-db semaphore; do
  cid="$(docker compose --env-file /etc/lifeos/semaphore.env -p "$PROJECT" -f "$CANONICAL" ps -q "$svc")"
  [[ -n "$cid" ]] || die "missing canonical service: $svc"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
  [[ "$health" == healthy ]] || die "$svc health=$health"
done

sem_cid="$(docker compose --env-file /etc/lifeos/semaphore.env -p "$PROJECT" -f "$CANONICAL" ps -q semaphore)"
new_dialect="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$sem_cid" | awk -F= '$1=="SEMAPHORE_DB_DIALECT"{print $2;exit}')"
[[ "$new_dialect" == postgres ]] || die "Semaphore did not switch to postgres"

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP/docker-ps.after.tsv"

# Custom execution path must remain untouched during shadow reconciliation.
for unit in lifeos-autonomous-agent.service lifeos-engineer.service lifeos-control-job-submit.socket lifeos-root-broker.socket; do
  systemctl is-active --quiet "$unit" || die "protected execution unit not active: $unit"
done

[[ -z "$(git -C "$PLATFORM" status --porcelain)" ]] || die "lifeos-platform became dirty"

cat <<EOF

RESULT=PASS
SEMAPHORE_SHADOW_RECONCILED=YES
OLD_DB_DIALECT=sqlite
NEW_DB_DIALECT=postgres
CANONICAL_SERVICES=2
CUSTOM_EXECUTION_PATH_CHANGED=NO
OLD_SQLITE_VOLUMES_DELETED=NO
BACKUP=$BACKUP
NEXT_ACTION=audit_replacement_scope_before_disabling_custom_orchestration
EOF
