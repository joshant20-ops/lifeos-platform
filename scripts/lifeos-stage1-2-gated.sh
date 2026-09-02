#!/usr/bin/env bash
set -Eeuo pipefail

# LifeOS Stage 1 + 2 gated cleanup
# Stage 1: retire agreed dead-weight services from the live Pi safely.
# Stage 2: reconcile lifeos-platform desired state, repair compose_projects.json,
#          and validate the repository before any optional commit/push.
#
# Safety properties:
# - Fail closed.
# - Never runs `docker compose down -v`.
# - Never deletes named Docker volumes.
# - Never deletes application data directories.
# - Backs up affected live stack directories and repo files first.
# - Does not touch Autoheal, Home Assistant, MQTT, Paperless, AdGuard,
#   Vaultwarden, VPN, Matter, Z-Wave, Predbat, LifeOS Energy, NPM or Uptime Kuma.
# - Git commit and push require separate explicit confirmation.
#
# Run:
#   chmod +x lifeos-stage1-2-gated.sh
#   ./lifeos-stage1-2-gated.sh
#
# Optional:
#   LIFEOS_REPO=/path/to/lifeos-platform ./lifeos-stage1-2-gated.sh
#
# Designed for the current Pi5/Debian 13 LifeOS layout.

SCRIPT_NAME="$(basename -- "$0")"
STAMP="$(date +%Y%m%d-%H%M%S)"
HOST="$(hostname)"
BACKUP_ROOT="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/stage1-2-${STAMP}}"
RETIRE_ROOT="${LIFEOS_RETIRE_ROOT:-/opt/stacks-retired/${STAMP}}"
LOG="${BACKUP_ROOT}/run.log"

TARGET_PROJECTS=(
  "privacy-guardian"
  "grafana"
  "prometheus"
  "watchtower"
  "portainer"
)

TARGET_CONTAINERS=(
  "privacy-guardian"
  "grafana"
  "prometheus"
  "cadvisor"
  "node-exporter"
  "watchtower"
  "portainer"
)

CORE_CANDIDATES=(
  "homeassistant"
  "mosquitto"
  "adguardhome"
  "vaultwarden"
  "matter-server"
  "zwave-js-ui"
  "predbat"
  "lifeos-energy"
  "nginx-proxy-manager"
  "uptime-kuma"
)

MANIFEST_REL="ansible/vars/compose_projects.json"
DESIRED_ROOT_REL="ansible/desired/compose"

say()   { printf '\n==> %s\n' "$*"; }
info()  { printf '    %s\n' "$*"; }
warn()  { printf 'WARN: %s\n' "$*" >&2; }
die()   { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

on_err() {
  local rc=$?
  printf '\nFAILED at line %s (exit %s).\n' "${BASH_LINENO[0]:-unknown}" "$rc" >&2
  printf 'No Docker volumes were intentionally deleted.\n' >&2
  if [[ -d "${BACKUP_ROOT:-}" ]]; then
    printf 'Recovery bundle: %s\n' "$BACKUP_ROOT" >&2
  fi
  exit "$rc"
}
trap on_err ERR

gate() {
  local prompt="$1"
  local answer
  printf '\nGATE: %s\n' "$prompt"
  printf "Type EXACTLY 'YES' to continue: "
  read -r answer
  [[ "$answer" == "YES" ]] || die "Gate declined."
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

container_exists() {
  docker inspect "$1" >/dev/null 2>&1
}

container_running() {
  [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" == "true" ]]
}

health_value() {
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || true
}

if [[ "${EUID}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -E bash "$0" "$@"
  fi
  die "Run as root (or install/use sudo)."
fi

mkdir -p "$BACKUP_ROOT" "$RETIRE_ROOT"
touch "$LOG"
exec > >(tee -a "$LOG") 2>&1

say "LifeOS Stage 1 + 2 gated cleanup"
info "Host:          $HOST"
info "Timestamp:     $STAMP"
info "Backup root:   $BACKUP_ROOT"
info "Retire root:   $RETIRE_ROOT"
info "Script:        $SCRIPT_NAME"

say "GATE 0 — Preflight"

for c in docker git python3; do need "$c"; done
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin is required."
docker info >/dev/null 2>&1 || die "Docker daemon is not reachable."

if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  info "OS: ${PRETTY_NAME:-unknown}"
  [[ "${ID:-}" == "debian" ]] || warn "Expected Debian; detected ${ID:-unknown}."
  [[ "${VERSION_ID:-}" == "13" ]] || warn "Expected Debian 13; detected ${VERSION_ID:-unknown}."
fi

ARCH="$(uname -m)"
info "Architecture: $ARCH"
[[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] || warn "Expected ARM64 Pi host; detected $ARCH."

find_repo() {
  local candidates=()
  [[ -n "${LIFEOS_REPO:-}" ]] && candidates+=("$LIFEOS_REPO")
  candidates+=(
    "$PWD"
    "/mnt/docker-data/automation/repos/lifeos-platform"
    "/mnt/docker-data/automation/repos/LifeOS-Platform"
    "/home/joshan/lifeos-platform"
    "/home/joshan/repos/lifeos-platform"
    "/opt/lifeos-platform"
  )

  local p
  for p in "${candidates[@]}"; do
    if [[ -d "$p/.git" && -f "$p/$MANIFEST_REL" && -d "$p/$DESIRED_ROOT_REL" ]]; then
      printf '%s\n' "$(readlink -f "$p")"
      return 0
    fi
  done

  while IFS= read -r p; do
    if [[ -f "$p/$MANIFEST_REL" && -d "$p/$DESIRED_ROOT_REL" ]]; then
      printf '%s\n' "$(readlink -f "$p")"
      return 0
    fi
  done < <(find /mnt/docker-data/automation/repos /home/joshan /opt \
      -maxdepth 3 -type d -name lifeos-platform 2>/dev/null | head -n 10)

  return 1
}

REPO="$(find_repo)" || die "Could not locate lifeos-platform. Re-run with LIFEOS_REPO=/path/to/lifeos-platform."
info "Repository:    $REPO"

cd "$REPO"
git rev-parse --is-inside-work-tree >/dev/null
BRANCH="$(git branch --show-current)"
HEAD_BEFORE="$(git rev-parse HEAD)"
REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
info "Git branch:    ${BRANCH:-DETACHED}"
info "Git HEAD:      $HEAD_BEFORE"
info "Git remote:    ${REMOTE_URL:-none}"

[[ "$BRANCH" == "main" ]] || die "Expected lifeos-platform main branch; current branch is '${BRANCH:-detached}'."

if [[ -n "$(git status --porcelain)" ]]; then
  warn "Repository already has uncommitted changes:"
  git status --short
  gate "Repository is dirty. Continue while preserving the existing changes?"
fi

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP_ROOT/docker-ps-before.tsv"
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP_ROOT/docker-ps-a-before.tsv"
docker network ls > "$BACKUP_ROOT/docker-networks-before.txt"
docker volume ls > "$BACKUP_ROOT/docker-volumes-before.txt"

: > "$BACKUP_ROOT/core-running-before.txt"
for c in "${CORE_CANDIDATES[@]}"; do
  if container_running "$c"; then
    printf '%s\n' "$c" >> "$BACKUP_ROOT/core-running-before.txt"
  fi
done

info "Core containers currently running:"
if [[ -s "$BACKUP_ROOT/core-running-before.txt" ]]; then
  sed 's/^/    - /' "$BACKUP_ROOT/core-running-before.txt"
else
  info "(none of the expected names detected; this is unusual)"
fi

info "Target containers currently present:"
for c in "${TARGET_CONTAINERS[@]}"; do
  if container_exists "$c"; then
    printf '    - %-20s running=%-5s health=%s\n' \
      "$c" \
      "$(container_running "$c" && echo true || echo false)" \
      "$(health_value "$c")"
  else
    printf '    - %-20s absent\n' "$c"
  fi
done

gate "Preflight passed. Create recovery backups before changing anything?"

say "GATE 1 — Recovery backup"

mkdir -p "$BACKUP_ROOT/repo" "$BACKUP_ROOT/live-stacks"

cp -a "$MANIFEST_REL" "$BACKUP_ROOT/repo/compose_projects.json.before"

for p in "${TARGET_PROJECTS[@]}"; do
  d="$DESIRED_ROOT_REL/$p"
  if [[ -e "$d" ]]; then
    mkdir -p "$BACKUP_ROOT/repo/desired-compose"
    cp -a "$d" "$BACKUP_ROOT/repo/desired-compose/"
  fi
done

git status --short > "$BACKUP_ROOT/repo/git-status-before.txt"
git diff > "$BACKUP_ROOT/repo/git-diff-before.patch" || true
printf '%s\n' "$HEAD_BEFORE" > "$BACKUP_ROOT/repo/git-head-before.txt"

for p in "${TARGET_PROJECTS[@]}"; do
  live="/opt/stacks/$p"
  if [[ -d "$live" ]]; then
    info "Backing up $live"
    cp -a "$live" "$BACKUP_ROOT/live-stacks/"
  else
    info "$live absent; no live stack directory to back up."
  fi
done

if [[ -d /opt/portainer ]]; then
  printf '/opt/portainer\n' > "$BACKUP_ROOT/portainer-data-preserved.txt"
fi

sync
info "Recovery bundle created at: $BACKUP_ROOT"
gate "Recovery bundle exists. Proceed to retire only the agreed Stage-1 services?"

say "GATE 2 — Retire live services"

retire_project() {
  local project="$1"
  local dir="/opt/stacks/$project"
  local compose=""

  if [[ -f "$dir/docker-compose.yml" ]]; then
    compose="$dir/docker-compose.yml"
  elif [[ -f "$dir/compose.yml" ]]; then
    compose="$dir/compose.yml"
  elif [[ -f "$dir/compose.yaml" ]]; then
    compose="$dir/compose.yaml"
  fi

  if [[ -n "$compose" ]]; then
    info "Stopping project '$project' via Docker Compose (NO -v)."
    docker compose -p "$project" -f "$compose" down --remove-orphans
  else
    warn "No Compose file found for '$project'; will fall back to named-container removal where applicable."
  fi
}

for p in "${TARGET_PROJECTS[@]}"; do
  retire_project "$p"
done

for c in "${TARGET_CONTAINERS[@]}"; do
  if container_exists "$c"; then
    warn "Container '$c' still exists after Compose down; stopping/removing container only."
    docker stop -t 20 "$c" >/dev/null 2>&1 || true
    docker rm "$c" >/dev/null
  fi
done

left=0
for c in "${TARGET_CONTAINERS[@]}"; do
  if container_exists "$c"; then
    warn "Target container still exists: $c"
    left=1
  fi
done
[[ "$left" -eq 0 ]] || die "Not all target containers were retired."

for p in "${TARGET_PROJECTS[@]}"; do
  src="/opt/stacks/$p"
  if [[ -d "$src" ]]; then
    info "Moving retired stack directory: $src -> $RETIRE_ROOT/$p"
    mv "$src" "$RETIRE_ROOT/$p"
  fi
done

info "No Docker volumes have been intentionally removed."

say "GATE 3 — Core-service survival check"

sleep 5
core_failed=0
while IFS= read -r c; do
  [[ -n "$c" ]] || continue
  if ! container_running "$c"; then
    warn "Core container that was running before cleanup is no longer running: $c"
    core_failed=1
    continue
  fi
  h="$(health_value "$c")"
  if [[ "$h" == "unhealthy" ]]; then
    warn "Core container is unhealthy: $c"
    core_failed=1
  else
    printf 'PASS: %-24s running health=%s\n' "$c" "$h"
  fi
done < "$BACKUP_ROOT/core-running-before.txt"

if [[ "$core_failed" -ne 0 ]]; then
  die "Core survival gate failed. Use recovery bundle $BACKUP_ROOT and retired stacks $RETIRE_ROOT."
fi

docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP_ROOT/docker-ps-after-retire.tsv"

gate "Stage 1 passed: agreed services are retired and surviving core services are still running. Proceed to repair desired state?"

say "GATE 4 — Desired-state reconciliation"

for p in "${TARGET_PROJECTS[@]}"; do
  d="$DESIRED_ROOT_REL/$p"
  if [[ -e "$d" ]]; then
    info "Removing desired-state directory from working tree: $d"
    rm -rf -- "$d"
  else
    info "Desired-state directory already absent: $d"
  fi
done

python3 - "$MANIFEST_REL" "${TARGET_PROJECTS[@]}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
targets = set(sys.argv[2:])

data = json.loads(path.read_text())

def keep(item):
    return item.get("project") not in targets

before_projects = len(data.get("compose_projects", []))
before_files = len(data.get("compose_files", []))

data["compose_projects"] = [x for x in data.get("compose_projects", []) if keep(x)]
data["compose_files"] = [x for x in data.get("compose_files", []) if keep(x)]

path.write_text(json.dumps(data, indent=2) + "\n")

print(f"compose_projects: {before_projects} -> {len(data['compose_projects'])}")
print(f"compose_files:    {before_files} -> {len(data['compose_files'])}")
PY

python3 - "$MANIFEST_REL" "$DESIRED_ROOT_REL" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
desired_root = pathlib.Path(sys.argv[2])
data = json.loads(manifest_path.read_text())

errors = []

projects = {x["project"]: x for x in data.get("compose_projects", [])}
files = data.get("compose_files", [])

for item in files:
    rel = item.get("desired_rel")
    if not rel:
        errors.append(f"{item.get('project')}: compose_files entry has no desired_rel")
        continue
    p = pathlib.Path("ansible") / rel
    if not p.exists():
        errors.append(f"{item.get('project')}: missing desired file {p}")

for name, item in projects.items():
    for rel in item.get("desired_files", []):
        p = pathlib.Path("ansible") / rel
        if not p.exists():
            errors.append(f"{name}: missing desired file {p}")

actual = {}
for d in desired_root.iterdir():
    if not d.is_dir():
        continue
    yamls = list(d.glob("*.yml")) + list(d.glob("*.yaml"))
    if yamls:
        actual[d.name] = yamls

manifest_names = set(projects)
actual_names = set(actual)

for name in sorted(actual_names - manifest_names):
    errors.append(f"desired Compose project exists but is missing from manifest: {name}")
for name in sorted(manifest_names - actual_names):
    errors.append(f"manifest project has no desired Compose YAML directory: {name}")

if errors:
    print("DESIRED-STATE CONSISTENCY: FAIL")
    for e in errors:
        print(f" - {e}")
    raise SystemExit(1)

print(f"DESIRED-STATE CONSISTENCY: PASS ({len(actual_names)} projects)")
PY

for p in "${TARGET_PROJECTS[@]}"; do
  if grep -q "\"project\": \"$p\"" "$MANIFEST_REL"; then
    die "Manifest still contains target project: $p"
  fi
  [[ ! -e "$DESIRED_ROOT_REL/$p" ]] || die "Desired-state target still exists: $p"
done

say "GATE 5 — Repository validation"

python3 -m json.tool "$MANIFEST_REL" >/dev/null
info "PASS: compose_projects.json parses."

compose_fail=0
while IFS= read -r f; do
  printf 'Validate: %s\n' "$f"
  if ! docker compose -f "$f" config -q; then
    warn "Compose validation failed: $f"
    compose_fail=1
  fi
done < <(find "$DESIRED_ROOT_REL" -type f \( -name '*.yml' -o -name '*.yaml' \) -print | sort)
[[ "$compose_fail" -eq 0 ]] || die "One or more desired Compose files are invalid."

if command -v ansible-playbook >/dev/null 2>&1; then
  ansible-playbook -i ansible/inventory.ini ansible/site.yml --syntax-check
  ansible-playbook -i ansible/inventory.ini ansible/adopt_all.yml --syntax-check
  info "PASS: Ansible syntax checks."
else
  warn "ansible-playbook is not installed on this host; Ansible syntax validation skipped."
  warn "GitHub CI should still run the repository's Ansible syntax checks."
fi

[[ -e "$DESIRED_ROOT_REL/autoheal" ]] || die "Autoheal desired state unexpectedly missing; Stage 1 was not supposed to remove it."

say "Proposed repository changes"
git status --short
printf '\nDiff summary:\n'
git diff --stat
printf '\nRelevant diff:\n'
git diff -- "$MANIFEST_REL" "$DESIRED_ROOT_REL" || true

git status --short > "$BACKUP_ROOT/repo/git-status-after.txt"
git diff > "$BACKUP_ROOT/repo/git-diff-after.patch" || true
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | sort > "$BACKUP_ROOT/docker-ps-a-final.tsv"

gate "Stage 2 validation passed. Keep these repo changes and proceed to the optional Git commit gate?"

say "GATE 6 — Optional Git commit"

printf "Create a local Git commit for ONLY the Stage 1/2 paths? [type COMMIT to proceed]: "
read -r commit_answer

if [[ "$commit_answer" == "COMMIT" ]]; then
  git add -- "$MANIFEST_REL"

  for p in "${TARGET_PROJECTS[@]}"; do
    git add -A -- "$DESIRED_ROOT_REL/$p" 2>/dev/null || true
  done

  if git diff --cached --quiet; then
    info "No Stage 1/2 repository changes remain to commit."
  else
    git diff --cached --check
    git commit -m "chore: complete LifeOS stage 1-2 cleanup"
    NEW_HEAD="$(git rev-parse HEAD)"
    info "Created commit: $NEW_HEAD"

    printf "Push this commit to origin/${BRANCH}? [type PUSH to proceed]: "
    read -r push_answer
    if [[ "$push_answer" == "PUSH" ]]; then
      git push origin "$BRANCH"
      info "Pushed origin/$BRANCH."
    else
      info "Push skipped. Commit exists locally only."
    fi
  fi
else
  info "Commit skipped. Validated changes remain in the working tree."
fi

say "FINAL GATE — Result"

for c in "${TARGET_CONTAINERS[@]}"; do
  container_exists "$c" && die "Final check: retired container unexpectedly exists: $c"
done

while IFS= read -r c; do
  [[ -n "$c" ]] || continue
  container_running "$c" || die "Final check: core container is not running: $c"
done < "$BACKUP_ROOT/core-running-before.txt"

cat <<EOF

PASS — LifeOS Stage 1 + Stage 2 gates completed.

Retired live services:
  privacy-guardian
  grafana
  prometheus
  cadvisor
  node-exporter
  watchtower
  portainer

Intentionally preserved:
  autoheal
  all Docker volumes
  Portainer persistent data at /opt/portainer (if present)
  Home Assistant / MQTT / Paperless / AdGuard / Vaultwarden
  VPN / Matter / Z-Wave / Predbat / LifeOS Energy / NPM / Uptime Kuma

Recovery bundle:
  $BACKUP_ROOT

Retired stack directories:
  $RETIRE_ROOT

Repository:
  $REPO

Current Git status:
EOF

git status --short || true

printf '\nIMPORTANT SECURITY FOLLOW-UP:\n'
printf '%s\n' \
  '  Revoke the old Gmail app password that was previously committed in the Grafana configuration.' \
  '  Deleting Grafana does not remove that secret from Git history.'

printf '\nDo NOT start Stage 3 until this system has remained stable and the core-service checks are satisfactory.\n'
