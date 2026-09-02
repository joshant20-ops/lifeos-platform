#!/usr/bin/env bash
set -euo pipefail

readonly JOB_ID=c3751aaff97b
readonly REPO="${LIFEOS_REPO_ROOT:-/opt/lifeos-platform}"
readonly COMPOSE="$REPO/orchestration/semaphore/docker-compose.yml"
readonly ENV_FILE=/etc/lifeos/semaphore.env
readonly PROJECT=lifeos-semaphore-shadow

finish() {
  printf 'ISSUE_VALIDITY=VALID\nLIFEOS_WORK_STATE=%s\nBARRIER=%s\nNEXT_AUTONOMOUS_ACTION=%s\nDISCOVERED_ISSUES_JSON_B64=none\nRESULT=%s\nTESTS=%s\nNEXT_RUNTIME_CHECK=%s\n' \
    "$1" "$2" "$3" "$4" "$5" "$6"
}
fail() {
  finish BLOCKED "$1" 'correct the named shadow barrier and rerun this launcher through Watchman' RETRY 'Semaphore shadow acceptance failed' 'rerun this launcher'
  exit 1
}
trap 'rc=$?; (( rc == 0 )) || true' EXIT

[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
[[ -f "$COMPOSE" ]] || fail semaphore_compose_missing
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail missing_root_owned_semaphore_env
[[ "$(stat -c '%U:%G:%a' "$ENV_FILE")" == root:root:600 ]] || fail unsafe_semaphore_env_permissions

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

printf 'SEMAPHORE_SHADOW=PASS version=v2.18.29 architecture=arm64 bind=%s compatibility_timer=%s\n' "$LIFEOS_SEMAPHORE_BIND_IP" "$compat_before"
finish PASS none 'add the allow-listed Ansible execution catalogue and structured Semaphore adapter' PASS 'compose contract, native ARM64 images, health, LAN and privilege boundaries PASS' 'verify persistence across Pi5 reboot and rehearse local backup/restore'
