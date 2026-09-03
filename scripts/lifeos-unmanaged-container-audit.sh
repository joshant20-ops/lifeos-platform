#!/usr/bin/env bash
set -Eeuo pipefail

TARGETS=(lifeos-engineer-ui lifeos-semaphore-shadow-semaphore-1)
PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"

echo "UNMANAGED_CONTAINER_AUDIT_VERSION=1"
echo "MUTATIONS=NONE"

echo
for c in "${TARGETS[@]}"; do
  echo "=== $c ==="
  if ! docker inspect "$c" >/dev/null 2>&1; then
    echo "present=no"
    echo
    continue
  fi

  docker inspect "$c" --format 'present=yes
state={{.State.Status}}
health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}
restart_count={{.RestartCount}}
image={{.Config.Image}}
created={{.Created}}
started={{.State.StartedAt}}
compose_project={{index .Config.Labels "com.docker.compose.project"}}
compose_working_dir={{index .Config.Labels "com.docker.compose.project.working_dir"}}
compose_config_files={{index .Config.Labels "com.docker.compose.project.config_files"}}
compose_service={{index .Config.Labels "com.docker.compose.service"}}
restart_policy={{.HostConfig.RestartPolicy.Name}}'

  echo "-- ports --"
  docker port "$c" 2>/dev/null || true

  echo "-- mounts --"
  docker inspect "$c" --format '{{range .Mounts}}{{printf "%s -> %s (%s,rw=%t)\n" .Source .Destination .Type .RW}}{{end}}'

  echo "-- networks --"
  docker inspect "$c" --format '{{range $k,$v := .NetworkSettings.Networks}}{{printf "%s ip=%s\n" $k $v.IPAddress}}{{end}}'

  echo "-- recent logs (last 50 lines) --"
  docker logs --tail 50 "$c" 2>&1 || true
  echo
done

echo "=== PLATFORM REFERENCES ==="
grep -RIn --exclude-dir=.git -E 'lifeos-engineer-ui|lifeos-semaphore-shadow|semaphore-shadow' "$PLATFORM" 2>/dev/null || true

echo
echo "=== SYSTEMD REFERENCES ==="
grep -RIn -E 'lifeos-engineer-ui|lifeos-semaphore-shadow|semaphore-shadow' /etc/systemd/system /usr/lib/systemd/system 2>/dev/null || true

echo
echo "=== RUNNING COMPOSE PROJECTS NOT IN DESIRED INVENTORY ==="
python3 - "$PLATFORM/ansible/vars/compose_projects.json" <<'PY'
import json, pathlib, subprocess, sys
manifest=json.loads(pathlib.Path(sys.argv[1]).read_text())
desired={x['project'] for x in manifest.get('compose_projects',[])}
out=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
projects={}
for name in out:
    try:
        raw=subprocess.check_output(['docker','inspect',name,'--format','{{index .Config.Labels "com.docker.compose.project"}}'],text=True).strip()
    except subprocess.CalledProcessError:
        raw=''
    if raw and raw not in desired:
        projects.setdefault(raw,[]).append(name)
for project,names in sorted(projects.items()):
    print(f'{project}: {", ".join(sorted(names))}')
PY

echo
echo "AUDIT_RESULT=PASS"
