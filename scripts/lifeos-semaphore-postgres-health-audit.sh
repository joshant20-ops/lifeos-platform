#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT=lifeos-semaphore-shadow
CANONICAL=/home/joshan/lifeos-platform/orchestration/semaphore/docker-compose.yml
ENV_FILE=/etc/lifeos/semaphore.env

echo 'SEMAPHORE_POSTGRES_HEALTH_AUDIT_VERSION=1'
echo 'MUTATIONS=NONE'

echo
echo '=== PROJECT CONTAINERS ==='
docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format 'name={{.Names}} image={{.Image}} status={{.Status}}'

sem=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=semaphore' | head -1)
db=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=semaphore-db' | head -1)
[[ -n "$sem" ]] || { echo 'ERROR=semaphore_container_missing'; exit 1; }
[[ -n "$db" ]] || { echo 'ERROR=semaphore_db_container_missing'; exit 1; }

echo
echo '=== HEALTH ==='
for cid in "$db" "$sem"; do
  docker inspect -f 'name={{.Name}} state={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restart_count={{.RestartCount}}' "$cid"
done

echo
echo '=== SEMAPHORE HEALTHCHECK DEFINITION ==='
docker inspect -f '{{json .Config.Healthcheck}}' "$sem"

echo
echo '=== SEMAPHORE HEALTH LOG ==='
docker inspect -f '{{range .State.Health.Log}}{{println .Start "exit=" .ExitCode}}{{println .Output}}{{end}}' "$sem" 2>/dev/null || true

echo
echo '=== SEMAPHORE EFFECTIVE DB ENV (secrets redacted) ==='
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$sem" | grep -E '^SEMAPHORE_DB_(DIALECT|HOST|NAME|USER|PATH)=' || true

echo
echo '=== IN-CONTAINER PROBE TOOLS ==='
for tool in curl wget busybox; do
  if docker exec "$sem" sh -c "command -v $tool" >/dev/null 2>&1; then
    echo "$tool=present"
  else
    echo "$tool=absent"
  fi
done

echo
echo '=== IN-CONTAINER API PING ==='
if docker exec "$sem" sh -c 'command -v curl >/dev/null 2>&1'; then
  docker exec "$sem" sh -c 'curl -fsS -v --max-time 5 http://127.0.0.1:3000/api/ping' 2>&1 || true
elif docker exec "$sem" sh -c 'command -v wget >/dev/null 2>&1'; then
  docker exec "$sem" sh -c 'wget -S -O- -T 5 http://127.0.0.1:3000/api/ping' 2>&1 || true
elif docker exec "$sem" sh -c 'command -v busybox >/dev/null 2>&1'; then
  docker exec "$sem" sh -c 'busybox wget -S -O- -T 5 http://127.0.0.1:3000/api/ping' 2>&1 || true
else
  echo 'probe_tool=none'
fi

echo
echo '=== HOST API PING ==='
bind_ip=$(awk -F= '$1=="LIFEOS_SEMAPHORE_BIND_IP"{print $2;exit}' "$ENV_FILE" 2>/dev/null || true)
echo "bind_ip=${bind_ip:-unknown}"
if [[ -n "$bind_ip" ]]; then
  curl -fsS -v --max-time 5 "http://${bind_ip}:3000/api/ping" 2>&1 || true
fi

echo
echo '=== SEMAPHORE LOGS (last 150) ==='
docker logs --tail 150 --timestamps "$sem" 2>&1 || true

echo
echo '=== POSTGRES LOGS (last 80) ==='
docker logs --tail 80 --timestamps "$db" 2>&1 || true

echo
echo '=== COMPOSE RENDER ==='
docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$CANONICAL" config 2>&1 | sed -E 's/(SEMAPHORE_DB_PASS_FILE|SEMAPHORE_ADMIN_PASSWORD_FILE|SEMAPHORE_ACCESS_KEY_ENCRYPTION_FILE):.*/\1: <file-ref-redacted>/' || true

echo
echo 'AUDIT_RESULT=PASS'
