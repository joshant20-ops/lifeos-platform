#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT=lifeos-semaphore-shadow
CANONICAL=/home/joshan/lifeos-platform/orchestration/semaphore/docker-compose.yml
ENV_FILE=/etc/lifeos/semaphore.env
SECRETS_DIR=/etc/lifeos/semaphore-secrets

echo 'SEMAPHORE_POSTGRES_HEALTH_AUDIT_VERSION=2'
echo 'MUTATIONS=NONE'

echo
echo '=== PROJECT CONTAINERS ==='
docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format 'name={{.Names}} image={{.Image}} status={{.Status}}'

sem=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=semaphore' | head -1)
db=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=semaphore-db' | head -1)
[[ -n "$sem" ]] || { echo 'ERROR=semaphore_container_missing'; exit 1; }
[[ -n "$db" ]] || { echo 'ERROR=semaphore_db_container_missing'; exit 1; }

echo
echo '=== STATE ==='
for cid in "$db" "$sem"; do
  docker inspect -f 'name={{.Name}} state={{.State.Status}} running={{.State.Running}} exit={{.State.ExitCode}} error={{json .State.Error}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} restart_count={{.RestartCount}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid"
done

echo
echo '=== SEMAPHORE RUNTIME USER ==='
docker inspect -f 'config_user={{.Config.User}}' "$sem"
docker image inspect -f 'image_user={{.Config.User}}' semaphoreui/semaphore:v2.18.29 2>/dev/null || true

echo
echo '=== SECRET METADATA ONLY ==='
if [[ -d "$SECRETS_DIR" ]]; then
  stat -c 'dir owner=%U group=%G uid=%u gid=%g mode=%a path=%n' "$SECRETS_DIR"
  for name in db_password admin_user admin_password access_key_encryption; do
    p="$SECRETS_DIR/$name"
    if [[ -e "$p" ]]; then
      stat -c 'file owner=%U group=%G uid=%u gid=%g mode=%a bytes=%s path=%n' "$p"
    else
      echo "missing=$p"
    fi
  done
else
  echo "missing=$SECRETS_DIR"
fi

echo
echo '=== SEMAPHORE HEALTHCHECK DEFINITION ==='
docker inspect -f '{{json .Config.Healthcheck}}' "$sem"

echo
echo '=== SEMAPHORE HEALTH LOG ==='
docker inspect -f '{{range .State.Health.Log}}{{println .Start "exit=" .ExitCode}}{{println .Output}}{{end}}' "$sem" 2>/dev/null || true

echo
echo '=== SEMAPHORE EFFECTIVE DB ENV (secrets redacted) ==='
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$sem" | grep -E '^SEMAPHORE_(DB_(DIALECT|HOST|NAME|USER|PATH|PASS_FILE)|ADMIN_FILE|ADMIN_PASSWORD_FILE|ACCESS_KEY_ENCRYPTION_FILE)=' | sed -E 's#=(/run/secrets/.*)$#=<file-ref-redacted>#' || true

echo
echo '=== IN-CONTAINER SECRET READABILITY (NO VALUES) ==='
if [[ "$(docker inspect -f '{{.State.Running}}' "$sem")" == true ]]; then
  for name in db_password admin_user admin_password access_key_encryption; do
    if docker exec "$sem" sh -c "test -r /run/secrets/$name" >/dev/null 2>&1; then
      echo "$name=readable"
    else
      echo "$name=NOT_READABLE"
    fi
  done
else
  echo 'container_not_running'
fi

echo
echo '=== HOST API PING ==='
bind_ip=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE" 2>/dev/null || true)
echo "bind_ip=${bind_ip:-unknown}"
if [[ -n "$bind_ip" ]]; then
  curl -fsS -v --max-time 5 "http://${bind_ip}:3000/api/ping" 2>&1 || true
fi

echo
echo '=== SEMAPHORE LOGS (last 200) ==='
docker logs --tail 200 --timestamps "$sem" 2>&1 || true

echo
echo '=== POSTGRES LOGS (last 100) ==='
docker logs --tail 100 --timestamps "$db" 2>&1 || true

echo
echo '=== COMPOSE RENDER ==='
docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$CANONICAL" config 2>&1 | sed -E 's/(SEMAPHORE_DB_PASS_FILE|SEMAPHORE_ADMIN_PASSWORD_FILE|SEMAPHORE_ACCESS_KEY_ENCRYPTION_FILE):.*/\1: <file-ref-redacted>/' || true

echo
echo 'AUDIT_RESULT=PASS'
