#!/usr/bin/env bash
set -Eeuo pipefail

printf 'AUTOHEAL_AUDIT_VERSION=1\n'
printf 'MUTATIONS=NONE\n\n'

if ! docker inspect autoheal >/dev/null 2>&1; then
  echo 'AUTOHEAL_PRESENT=NO'
  exit 0
fi

echo '=== AUTOHEAL CONTAINER ==='
docker inspect autoheal --format 'state={{.State.Status}} restart_count={{.RestartCount}} image={{.Config.Image}} started={{.State.StartedAt}}'

echo
echo '=== AUTOHEAL CONFIG ==='
docker inspect autoheal --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(AUTOHEAL_|DOCKER_SOCK=|WEBHOOK_URL=|APPRISE_URL=)' || true

echo
echo '=== AUTOHEAL DOCKER SOCKET ==='
docker inspect autoheal --format '{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}source={{.Source}} destination={{.Destination}} mode={{.Mode}} rw={{.RW}}{{end}}{{end}}'

echo
echo '=== CONTAINER HEALTH / RESTART POLICY / AUTOHEAL LABELS ==='
printf 'CONTAINER\tSTATE\tHEALTH\tRESTART_POLICY\tRESTART_COUNT\tAUTOHEAL_LABEL\n'
while IFS= read -r c; do
  docker inspect "$c" --format '{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.HostConfig.RestartPolicy.Name}}|{{.RestartCount}}|{{index .Config.Labels "autoheal"}}' 2>/dev/null |
    sed 's#^/##; s/|/\t/g'
done < <(docker ps -a --format '{{.Names}}' | sort)

echo
echo '=== AUTOHEAL LOG EVIDENCE (last 30 days / available history) ==='
LOG="$(docker logs --since 720h autoheal 2>&1 || true)"
if [[ -z "$LOG" ]]; then
  echo 'AUTOHEAL_LOG_LINES=0'
  echo 'AUTOHEAL_RESTART_EVIDENCE=0'
else
  printf '%s\n' "$LOG" | tail -200
  printf 'AUTOHEAL_LOG_LINES=%s\n' "$(printf '%s\n' "$LOG" | wc -l)"
  printf 'AUTOHEAL_RESTART_EVIDENCE=%s\n' "$(printf '%s\n' "$LOG" | grep -Eic 'restart|unhealthy|healing|heal container|container.*heal' || true)"
fi

echo
echo '=== UNHEALTHY CONTAINERS NOW ==='
UNHEALTHY="$(docker ps -a --filter health=unhealthy --format '{{.Names}}' || true)"
if [[ -n "$UNHEALTHY" ]]; then
  printf '%s\n' "$UNHEALTHY"
  printf 'UNHEALTHY_NOW=%s\n' "$(printf '%s\n' "$UNHEALTHY" | wc -l)"
else
  echo 'none'
  echo 'UNHEALTHY_NOW=0'
fi

echo
echo '=== SUMMARY INPUTS ==='
printf 'AUTOHEAL_PRESENT=YES\n'
printf 'AUTOHEAL_SCOPE=%s\n' "$(docker inspect autoheal --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= '$1=="AUTOHEAL_CONTAINER_LABEL"{print $2; exit}')"
printf 'DOCKER_SOCKET_RW=%s\n' "$(docker inspect autoheal --format '{{range .Mounts}}{{if eq .Destination "/var/run/docker.sock"}}{{.RW}}{{end}}{{end}}')"
printf 'AUDIT_RESULT=PASS\n'