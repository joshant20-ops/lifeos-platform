#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
ENV_FILE=/etc/lifeos/semaphore.env
SECRETS=/etc/lifeos/semaphore-secrets
PROJECT=lifeos-semaphore-shadow
COMPOSE=/opt/stacks/lifeos-semaphore-shadow/docker-compose.yml
BACKUP_ROOT=/mnt/docker-data/automation/backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$BACKUP_ROOT/semaphore-recovery-$STAMP"
DUMP="$BACKUP/semaphore.sql"
META_BEFORE="$BACKUP/runtime-before.txt"
META_AFTER="$BACKUP/runtime-after.txt"
SCRATCH="lifeos_semaphore_restore_${STAMP//-/}"

[[ $EUID -eq 0 ]] || { echo 'ERROR: run via sudo'; exit 1; }
[[ -r "$ENV_FILE" ]] || { echo 'ERROR: Semaphore env missing'; exit 1; }
[[ -r "$SECRETS/admin_user" && -r "$SECRETS/admin_password" ]] || { echo 'ERROR: Semaphore bootstrap credentials missing'; exit 1; }
[[ -r "$COMPOSE" ]] || { echo "ERROR: live Semaphore compose missing: $COMPOSE"; exit 1; }
[[ -d "$PLATFORM/.git" ]] || { echo 'ERROR: platform repository missing'; exit 1; }

HEAD=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || { echo 'ERROR: platform HEAD is not origin/main'; exit 1; }
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository dirty'; exit 1; }
[[ "$(stat -c '%U:%G' "$PLATFORM/.git/index")" == 'joshan:joshan' ]] || { echo 'ERROR: git metadata ownership invalid'; exit 1; }

BIND_IP=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE")
[[ -n "$BIND_IP" ]] || { echo 'ERROR: Semaphore bind IP missing'; exit 1; }
BASE="http://${BIND_IP}:3000/api"

mkdir -p "$BACKUP"
chmod 0700 "$BACKUP"

cleanup() {
  docker exec "${PROJECT}-semaphore-db-1" psql -U semaphore -d postgres -v ON_ERROR_STOP=1 -Atqc \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${SCRATCH}' AND pid<>pg_backend_pid();" >/dev/null 2>&1 || true
  docker exec "${PROJECT}-semaphore-db-1" psql -U semaphore -d postgres -v ON_ERROR_STOP=1 -Atqc \
    "DROP DATABASE IF EXISTS \"${SCRATCH}\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

printf '%s\n' 'SEMAPHORE_RECOVERY_REHEARSAL_VERSION=1'
printf 'PLATFORM_HEAD=%s\n' "$HEAD"
printf 'BACKUP=%s\n' "$BACKUP"
printf '%s\n' 'MUTATIONS=SEMAPHORE_RESTART_AND_TEMPORARY_SCRATCH_DATABASE_ONLY'
printf '%s\n' 'LIVE_DATABASE_OVERWRITE=NO'

# Require the live stack to be healthy enough to rehearse safely.
[[ "$(docker inspect -f '{{.State.Status}}' "${PROJECT}-semaphore-db-1" 2>/dev/null)" == running ]] || { echo 'ERROR: Semaphore PostgreSQL is not running'; exit 1; }
[[ "$(docker inspect -f '{{.State.Health.Status}}' "${PROJECT}-semaphore-db-1" 2>/dev/null)" == healthy ]] || { echo 'ERROR: Semaphore PostgreSQL is not healthy'; exit 1; }
curl -fsS --max-time 5 "$BASE/ping" >/dev/null || { echo 'ERROR: Semaphore API unavailable before rehearsal'; exit 1; }

# Capture live catalogue/history counts through the authenticated API without exposing credentials.
export LIFEOS_SEMAPHORE_BASE="$BASE" LIFEOS_SEMAPHORE_ADMIN_USER_FILE="$SECRETS/admin_user" LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE="$SECRETS/admin_password"
python3 - "$META_BEFORE" <<'PY'
import http.cookiejar,json,os,pathlib,sys,urllib.request
base=os.environ['LIFEOS_SEMAPHORE_BASE'].rstrip('/')
login=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_USER_FILE']).read_text().strip()
password=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE']).read_text().strip()
jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def req(method,path,body=None):
    data=None if body is None else json.dumps(body).encode(); h={'Accept':'application/json'}
    if body is not None: h['Content-Type']='application/json'
    with op.open(urllib.request.Request(base+path,data=data,headers=h,method=method),timeout=15) as r:
        raw=r.read(); return json.loads(raw) if raw else None
req('POST','/auth/login',{'auth':login,'password':password})
projects=req('GET','/projects') or []
summary={'projects':len(projects),'project_ids':sorted(int(p['id']) for p in projects)}
templates=tasks=0
for p in projects:
    pid=int(p['id'])
    templates += len(req('GET',f'/project/{pid}/templates') or [])
    t=req('GET',f'/project/{pid}/tasks?limit=100') or []
    if isinstance(t,dict): t=t.get('tasks',t.get('items',[]))
    tasks += len(t)
summary.update({'templates':templates,'tasks_observed':tasks})
pathlib.Path(sys.argv[1]).write_text(json.dumps(summary,sort_keys=True)+'\n')
print('CATALOGUE_BEFORE='+json.dumps(summary,separators=(',',':')))
PY
chmod 0600 "$META_BEFORE"

# Create a root-only logical backup. No live database mutation is required for pg_dump.
echo '=== LOGICAL BACKUP ==='
docker exec "${PROJECT}-semaphore-db-1" pg_dump -U semaphore -d semaphore --no-owner --no-privileges >"$DUMP"
chmod 0600 "$DUMP"
[[ -s "$DUMP" ]] || { echo 'ERROR: logical backup is empty'; exit 1; }
DUMP_SHA=$(sha256sum "$DUMP" | awk '{print $1}')
echo "BACKUP_SHA256=$DUMP_SHA"
echo "BACKUP_BYTES=$(stat -c '%s' "$DUMP")"

# Restart only the Semaphore Compose project. No image pull and no volume deletion.
echo '=== STACK RESTART ==='
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
docker compose -p "$PROJECT" -f "$COMPOSE" restart

for _ in $(seq 1 60); do
  DB_STATE=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${PROJECT}-semaphore-db-1" 2>/dev/null || true)
  if [[ "$DB_STATE" == healthy ]] && curl -fsS --max-time 3 "$BASE/ping" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
[[ "$(docker inspect -f '{{.State.Health.Status}}' "${PROJECT}-semaphore-db-1" 2>/dev/null)" == healthy ]] || { echo 'ERROR: PostgreSQL did not recover healthy after restart'; exit 1; }
curl -fsS --max-time 5 "$BASE/ping" >/dev/null || { echo 'ERROR: Semaphore API did not recover after restart'; exit 1; }
echo 'RESTART_RECOVERY=PASS'

# Re-read catalogue/history and require persistence.
python3 - "$META_AFTER" <<'PY'
import http.cookiejar,json,os,pathlib,sys,urllib.request
base=os.environ['LIFEOS_SEMAPHORE_BASE'].rstrip('/')
login=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_USER_FILE']).read_text().strip()
password=pathlib.Path(os.environ['LIFEOS_SEMAPHORE_ADMIN_PASSWORD_FILE']).read_text().strip()
jar=http.cookiejar.CookieJar(); op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def req(method,path,body=None):
    data=None if body is None else json.dumps(body).encode(); h={'Accept':'application/json'}
    if body is not None: h['Content-Type']='application/json'
    with op.open(urllib.request.Request(base+path,data=data,headers=h,method=method),timeout=15) as r:
        raw=r.read(); return json.loads(raw) if raw else None
req('POST','/auth/login',{'auth':login,'password':password})
projects=req('GET','/projects') or []
summary={'projects':len(projects),'project_ids':sorted(int(p['id']) for p in projects)}
templates=tasks=0
for p in projects:
    pid=int(p['id']); templates += len(req('GET',f'/project/{pid}/templates') or [])
    t=req('GET',f'/project/{pid}/tasks?limit=100') or []
    if isinstance(t,dict): t=t.get('tasks',t.get('items',[]))
    tasks += len(t)
summary.update({'templates':templates,'tasks_observed':tasks})
pathlib.Path(sys.argv[1]).write_text(json.dumps(summary,sort_keys=True)+'\n')
print('CATALOGUE_AFTER='+json.dumps(summary,separators=(',',':')))
PY
chmod 0600 "$META_AFTER"
cmp -s "$META_BEFORE" "$META_AFTER" || { echo 'ERROR: Semaphore catalogue/history changed across restart'; diff -u "$META_BEFORE" "$META_AFTER" || true; exit 1; }
echo 'PERSISTENCE_ACROSS_RESTART=PASS'

# Restore the logical backup into a temporary scratch DB in the same PostgreSQL engine.
# This validates that the backup is actually restorable without touching the live semaphore DB.
echo '=== ISOLATED RESTORE REHEARSAL ==='
docker exec "${PROJECT}-semaphore-db-1" psql -U semaphore -d postgres -v ON_ERROR_STOP=1 -Atqc "CREATE DATABASE \"${SCRATCH}\";"
cat "$DUMP" | docker exec -i "${PROJECT}-semaphore-db-1" psql -U semaphore -d "$SCRATCH" -v ON_ERROR_STOP=1 >/dev/null
LIVE_TABLES=$(docker exec "${PROJECT}-semaphore-db-1" psql -U semaphore -d semaphore -Atqc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")
RESTORE_TABLES=$(docker exec "${PROJECT}-semaphore-db-1" psql -U semaphore -d "$SCRATCH" -Atqc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")
[[ "$LIVE_TABLES" =~ ^[0-9]+$ && "$RESTORE_TABLES" =~ ^[0-9]+$ ]] || { echo 'ERROR: table-count verification failed'; exit 1; }
[[ "$LIVE_TABLES" -gt 0 && "$RESTORE_TABLES" == "$LIVE_TABLES" ]] || { echo "ERROR: restored table count mismatch live=$LIVE_TABLES restored=$RESTORE_TABLES"; exit 1; }
echo "LIVE_TABLES=$LIVE_TABLES"
echo "RESTORED_TABLES=$RESTORE_TABLES"
echo 'ISOLATED_RESTORE=PASS'

cleanup
trap - EXIT

[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || { echo 'ERROR: platform repository changed'; exit 1; }
[[ "$(stat -c '%U:%G' "$PLATFORM/.git/index")" == 'joshan:joshan' ]] || { echo 'ERROR: git metadata ownership changed'; exit 1; }

echo
echo 'RESULT=PASS'
echo 'SEMAPHORE_RESTART_PERSISTENCE=PASS'
echo 'SEMAPHORE_LOGICAL_BACKUP=PASS'
echo 'SEMAPHORE_ISOLATED_RESTORE=PASS'
echo 'LIVE_DATABASE_OVERWRITE=NO'
echo 'BACKUP_RETAINED=YES'
echo "BACKUP=$BACKUP"
echo 'PLATFORM_MUTATION=NONE'
echo 'CUSTOM_BACKLOG_AUTHORITY_CHANGED=NO'
echo 'NEXT_ACTION=audit_legacy_dispatcher_retirement_preconditions'
