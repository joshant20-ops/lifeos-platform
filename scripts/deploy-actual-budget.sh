#!/usr/bin/env bash
set -Eeuo pipefail
repo_root="${GITHUB_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
src="$repo_root/ansible/desired/compose/actual-budget/docker-compose.yml"
dst="/opt/stacks/actual-budget/docker-compose.yml"
data_root="/mnt/docker-data"
data_dir="$data_root/actual-budget"

test -f "$src"
mountpoint -q "$data_root" || { echo "REFUSE: $data_root is not a mounted filesystem"; exit 20; }
install -d -o joshan -g joshan -m 0750 /opt/stacks/actual-budget "$data_dir"
install -o joshan -g joshan -m 0644 "$src" "$dst"
cd /opt/stacks/actual-budget
docker compose pull
docker compose up -d
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:5006/ >/dev/null; then
    findmnt -T "$data_dir" -n -o TARGET,SOURCE,FSTYPE
    exit 0
  fi
  sleep 2
done
docker compose ps
exit 1
