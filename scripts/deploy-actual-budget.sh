#!/usr/bin/env bash
set -Eeuo pipefail
src="/home/joshan/lifeos-platform/ansible/desired/compose/actual-budget/docker-compose.yml"
dst="/opt/stacks/actual-budget/docker-compose.yml"
install -d -o joshan -g joshan -m 0750 /opt/stacks/actual-budget /opt/stacks/actual-budget/data
install -o joshan -g joshan -m 0644 "$src" "$dst"
cd /opt/stacks/actual-budget
docker compose pull
docker compose up -d
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:5006/ >/dev/null; then exit 0; fi
  sleep 2
done
docker compose ps
exit 1
