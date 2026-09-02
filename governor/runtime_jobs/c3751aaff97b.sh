#!/usr/bin/env bash
set -euo pipefail

readonly JOB_ID=c3751aaff97b
# Pi5 owns the canonical checkout at this fixed path.  The previous /opt
# default made a correctly published shadow fail as semaphore_compose_missing
# before Compose could validate or start it.  Keep an explicit override for
# the local contract test only; Watchman uses the canonical default.
readonly REPO="${LIFEOS_REPO_ROOT:-/home/joshan/lifeos-platform}"
readonly COMPOSE="$REPO/orchestration/semaphore/docker-compose.yml"
readonly ENV_FILE=/etc/lifeos/semaphore.env
readonly PROJECT=lifeos-semaphore-shadow
readonly DEFAULT_SECRETS_DIR=/etc/lifeos/semaphore-secrets

finish() {
  printf 'ISSUE_VALIDITY=VALID\nLIFEOS_WORK_STATE=%s\nBARRIER=%s\nNEXT_AUTONOMOUS_ACTION=%s\nDISCOVERED_ISSUES_JSON_B64=none\nRESULT=%s\nTESTS=%s\nNEXT_RUNTIME_CHECK=%s\n' \
    "$1" "$2" "$3" "$4" "$5" "$6"
}
fail() {
  finish BLOCKED "$1" 'correct the named shadow barrier and rerun this launcher through Watchman' RETRY 'Semaphore shadow acceptance failed' 'rerun this launcher'
  exit 1
}
trap 'rc=$?; (( rc == 0 )) || true' EXIT

private_lan_ip() {
  local candidate
  candidate=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}')
  [[ "$candidate" =~ ^10\. || "$candidate" =~ ^192\.168\. || "$candidate" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. ]] || return 1
  printf '%s\n' "$candidate"
}

create_secret() {
  local path=$1 kind=$2 value
  [[ ! -e "$path" ]] || return 0
  case "$kind" in
    admin_user) value=lifeos-admin ;;
    encryption) value=$(timeout 10s openssl rand -base64 32) || fail secret_generation_failed ;;
    password) value=$(timeout 10s openssl rand -base64 48) || fail secret_generation_failed ;;
    *) fail invalid_secret_kind ;;
  esac
  (umask 077; printf '%s\n' "$value" >"$path") || fail secret_file_creation_failed
}

bootstrap_first_run() {
  local bind_ip
  # A missing configuration is an expected first-deployment state, not a
  # human boundary. Watchman already grants this reviewed launcher root, so it
  # can create least-privilege local material without exposing any value.
  if [[ ! -e "$ENV_FILE" ]]; then
    bind_ip=$(private_lan_ip) || fail private_lan_ip_not_detected
    install -d -o root -g root -m 0755 /etc/lifeos || fail config_directory_creation_failed
    (umask 077; printf 'LIFEOS_SEMAPHORE_BIND_IP=%s\nLIFEOS_SEMAPHORE_SECRETS_DIR=%s\n' \
      "$bind_ip" "$DEFAULT_SECRETS_DIR" >"$ENV_FILE") || fail semaphore_env_creation_failed
  fi
  [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail missing_root_owned_semaphore_env
  [[ "$(stat -c '%U:%G:%a' "$ENV_FILE")" == root:root:600 ]] || fail unsafe_semaphore_env_permissions

  # shellcheck disable=SC1090
  source "$ENV_FILE"
  if [[ ! -e "${LIFEOS_SEMAPHORE_SECRETS_DIR:-}" ]]; then
    [[ "${LIFEOS_SEMAPHORE_SECRETS_DIR:-}" == "$DEFAULT_SECRETS_DIR" ]] || fail missing_semaphore_secrets_directory
    install -d -o root -g root -m 0700 "$DEFAULT_SECRETS_DIR" || fail secrets_directory_creation_failed
  fi
  [[ -d "${LIFEOS_SEMAPHORE_SECRETS_DIR:-}" && ! -L "$LIFEOS_SEMAPHORE_SECRETS_DIR" ]] || fail missing_semaphore_secrets_directory
  [[ "$(stat -c '%U:%G:%a' "$LIFEOS_SEMAPHORE_SECRETS_DIR")" == root:root:700 ]] || fail unsafe_semaphore_secrets_directory
  create_secret "$LIFEOS_SEMAPHORE_SECRETS_DIR/db_password" password
  create_secret "$LIFEOS_SEMAPHORE_SECRETS_DIR/admin_user" admin_user
  create_secret "$LIFEOS_SEMAPHORE_SECRETS_DIR/admin_password" password
  create_secret "$LIFEOS_SEMAPHORE_SECRETS_DIR/access_key_encryption" encryption
}

[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
[[ -d "$REPO/.git" ]] || fail canonical_pi5_checkout_missing
[[ -f "$COMPOSE" ]] || fail semaphore_compose_missing
# Runtime acceptance must describe published, immutable source rather than an
# ad-hoc edit in the Pi5 checkout.  This also turns a missed publication into a
# precise barrier before Docker state can change.
git -C "$REPO" ls-files --error-unmatch \
  "orchestration/semaphore/docker-compose.yml" \
  "governor/runtime_jobs/$JOB_ID.sh" >/dev/null 2>&1 || fail shadow_source_not_tracked
git -C "$REPO" diff --quiet HEAD -- \
  "orchestration/semaphore/docker-compose.yml" \
  "governor/runtime_jobs/$JOB_ID.sh" || fail shadow_source_not_published
source_commit=$(git -C "$REPO" rev-parse --verify HEAD) || fail source_commit_unavailable
[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || fail invalid_source_commit
bootstrap_first_run

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[[ -n "${LIFEOS_SEMAPHORE_BIND_IP:-}" && "$LIFEOS_SEMAPHORE_BIND_IP" != 0.0.0.0 ]] || fail unsafe_semaphore_bind_ip
[[ "$LIFEOS_SEMAPHORE_BIND_IP" != 127.* && "$LIFEOS_SEMAPHORE_BIND_IP" != ::1 ]] || fail bind_ip_not_lan
[[ "$LIFEOS_SEMAPHORE_BIND_IP" =~ ^10\. || "$LIFEOS_SEMAPHORE_BIND_IP" =~ ^192\.168\. || "$LIFEOS_SEMAPHORE_BIND_IP" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. || "$LIFEOS_SEMAPHORE_BIND_IP" =~ ^f[cd][0-9a-fA-F]{2}: ]] || fail bind_ip_not_private_lan
[[ -d "${LIFEOS_SEMAPHORE_SECRETS_DIR:-}" && ! -L "$LIFEOS_SEMAPHORE_SECRETS_DIR" ]] || fail missing_semaphore_secrets_directory
[[ "$(stat -c '%U:%G:%a' "$LIFEOS_SEMAPHORE_SECRETS_DIR")" == root:root:700 ]] || fail unsafe_semaphore_secrets_directory
for name in db_password admin_user admin_password access_key_encryption; do
  path="$LIFEOS_SEMAPHORE_SECRETS_DIR/$name"
  [[ -f "$path" && ! -L "$path" && -s "$path" ]] || fail "invalid_secret_file_$name"
  [[ "$(stat -c '%U:%G:%a' "$path")" == root:root:600 ]] || fail "unsafe_secret_permissions_$name"
done

compose=(docker compose --env-file "$ENV_FILE" -p "$PROJECT" -f "$COMPOSE")
timeout 30s "${compose[@]}" config --quiet || fail compose_contract_invalid
[[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] || fail host_not_arm64
timeout 300s "${compose[@]}" pull --quiet || fail image_pull_failed
for image in semaphoreui/semaphore:v2.18.29 postgres:17.6-bookworm; do
  [[ "$(docker image inspect -f '{{.Architecture}}' "$image")" == arm64 ]] || fail resolved_image_not_arm64
done

compat_before=$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)
timeout 180s "${compose[@]}" up -d || fail shadow_start_failed
for service in semaphore-db semaphore; do
  cid=$("${compose[@]}" ps -q "$service")
  [[ -n "$cid" ]] || fail "container_missing_$service"
  for _ in $(seq 1 30); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' "$cid")" == healthy ]] && break
    sleep 2
  done
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$cid")" == healthy ]] || fail "container_unhealthy_$service"
  if [[ "$service" == semaphore ]]; then
    user=$(docker inspect -f '{{.Config.User}}' "$cid")
    [[ -n "$user" && "$user" != root && "$user" != 0 ]] || fail semaphore_runs_as_root
  fi
  mounts=$(docker inspect -f '{{range .Mounts}}{{.Destination}} {{end}}' "$cid")
  [[ "$mounts" != *docker.sock* && "$mounts" != *lifeos-transactions* && "$mounts" != *'/root'* ]] || fail "privileged_mount_$service"
done

semaphore_id=$("${compose[@]}" ps -q semaphore)
published=$(docker inspect -f '{{(index (index .NetworkSettings.Ports "3000/tcp") 0).HostIp}}' "$semaphore_id") || fail published_port_inspection_failed
[[ "$published" == "$LIFEOS_SEMAPHORE_BIND_IP" ]] || fail semaphore_not_lan_bound
[[ "$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)" == "$compat_before" ]] || fail compatibility_path_disturbed

printf 'SEMAPHORE_SHADOW=PASS job=%s source_commit=%s version=v2.18.29 architecture=arm64 bind=%s compatibility_timer=%s\n' "$JOB_ID" "$source_commit" "$LIFEOS_SEMAPHORE_BIND_IP" "$compat_before"
finish PASS none 'add the allow-listed Ansible execution catalogue and structured Semaphore adapter' PASS 'compose contract, native ARM64 images, health, LAN and privilege boundaries PASS' 'verify persistence across Pi5 reboot and rehearse local backup/restore'
