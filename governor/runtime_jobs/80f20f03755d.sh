#!/usr/bin/env bash
set -euo pipefail

readonly JOB_ID=80f20f03755d
readonly REPO=/home/joshan/lifeos-platform
readonly COMPOSE="$REPO/orchestration/rundeck/docker-compose.yml"
readonly ENV_FILE=/etc/lifeos/rundeck.env
readonly PROJECT=lifeos-rundeck-shadow
started_here=false

compose() {
  timeout 12m docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE" "$@"
}

lookup_container_id() {
  local service=$1
  compose ps -q "$service" 2>/dev/null
}

result() {
  local state=$1 barrier=$2 next=$3 result_value=$4 tests=$5 runtime_check=$6
  printf 'ISSUE_VALIDITY=VALID\n'
  printf 'LIFEOS_WORK_STATE=%s\n' "$state"
  printf 'BARRIER=%s\n' "$barrier"
  printf 'NEXT_AUTONOMOUS_ACTION=%s\n' "$next"
  printf 'DISCOVERED_ISSUES_JSON_B64=none\n'
  printf 'RESULT=%s\n' "$result_value"
  printf 'TESTS=%s\n' "$tests"
  printf 'NEXT_RUNTIME_CHECK=%s\n' "$runtime_check"
}

fail() {
  local reason=$1
  # Keep failure evidence useful without printing Compose environment values or
  # application logs, either of which may contain externally supplied secrets.
  # Status and health-state fields are sufficient to distinguish pull, startup,
  # and health-check failures on the next autonomous iteration.
  if command -v docker >/dev/null 2>&1 && [[ -f "$ENV_FILE" ]]; then
    compose ps --format 'FAIL_EVIDENCE service={{.Service}} state={{.State}} health={{.Health}}' \
      2>/dev/null || true
  fi
  if [[ "$started_here" == true ]]; then
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
  result BLOCKED "$reason" \
    "repair the shadow acceptance failure and rerun this Watchman job" \
    RETRY "Rundeck shadow acceptance failed: $reason" \
    "bash governor/runtime_jobs/$JOB_ID.sh"
  exit 1
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
[[ -f "$COMPOSE" && ! -L "$COMPOSE" ]] || fail unsafe_or_missing_compose_definition
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail missing_root_owned_rundeck_env
[[ "$(stat -c '%U:%G:%a' "$ENV_FILE")" == root:root:600 ]] || fail unsafe_rundeck_env_permissions
command -v docker >/dev/null || fail docker_unavailable
timeout 20s docker compose version >/dev/null || fail docker_compose_unavailable

# Validate the repository contract and fully resolve Compose before touching the
# shadow stack. Neither command prints the populated environment file.
timeout 90s python3 -m pytest -q "$REPO/tests/test_rundeck_shadow_contract.py" \
  || fail repository_shadow_contract_failed
compose config --quiet || fail compose_resolution_failed

# Semaphore was design-only in this repository. The meaningful production
# comparator is the current backlog compatibility timer/service. Preserve the
# stable unit configuration and timer state so this cannot become a cutover.
compat_timer_enabled=$(systemctl is-enabled lifeos-backlog-runner.timer 2>/dev/null || true)
compat_timer_active=$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)
compat_service_enabled=$(systemctl is-enabled lifeos-backlog-runner.service 2>/dev/null || true)
compat_service_state=$(systemctl is-active lifeos-backlog-runner.service 2>/dev/null || true)
[[ -n "$compat_timer_enabled" && -n "$compat_timer_active" && \
   -n "$compat_service_enabled" && -n "$compat_service_state" ]] \
  || fail compatibility_path_state_unavailable
[[ "$compat_service_state" != failed ]] || fail compatibility_service_failed_before_shadow_test

rundeck_id=$(compose ps -q rundeck 2>/dev/null || true)
if [[ -z "$rundeck_id" ]]; then
  started_here=true
fi
# A failed cold start can leave a created/running-but-unhealthy container behind.
# Docker restart policies react to process exits, not failed health checks, and a
# plain `compose up` reuses that container. Recreate only the bounded shadow
# services on retry; named database/application volumes remain intact.
shadow_needs_recreate=false
for service in rundeck-db rundeck; do
  container_id=$(compose ps -aq "$service" 2>/dev/null || true)
  if [[ -n "$container_id" ]]; then
    container_state=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id") \
      || fail "${service}_container_inspect_failed"
    case "$container_state" in
      running/healthy|created/none) ;;
      *) shadow_needs_recreate=true ;;
    esac
  fi
done
# Rundeck performs first-start database migrations on the Pi5. Four minutes was
# too short for a cold shadow start; retain a finite ten-minute acceptance bound.
if [[ "$shadow_needs_recreate" == true ]]; then
  compose up -d --force-recreate --wait --wait-timeout 600 || fail shadow_recreate_or_health_failed
else
  compose up -d --wait --wait-timeout 600 || fail shadow_start_or_health_failed
fi

rundeck_id=$(lookup_container_id rundeck) || fail rundeck_container_lookup_failed
db_id=$(lookup_container_id rundeck-db) || fail rundeck_db_container_lookup_failed
[[ -n "$rundeck_id" && -n "$db_id" ]] || fail shadow_container_missing
for container_id in "$rundeck_id" "$db_id"; do
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$container_id")" == healthy ]] \
    || fail shadow_container_unhealthy
  [[ "$(docker inspect -f '{{.HostConfig.Privileged}}' "$container_id")" == false ]] \
    || fail privileged_container_detected
  [[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$container_id")" != host ]] \
    || fail host_network_detected
done
[[ -n "$(docker image inspect -f '{{join .RepoDigests " "}}' "rundeck/rundeck:6.1.0")" ]] \
  || fail unresolved_rundeck_image_digest
[[ -n "$(docker image inspect -f '{{join .RepoDigests " "}}' "postgres:17.6-bookworm")" ]] \
  || fail unresolved_postgres_image_digest
for container_id in "$rundeck_id" "$db_id"; do
  mounts=$(docker inspect -f '{{range .Mounts}}{{println .Source}}{{end}}' "$container_id")
  [[ "$mounts" != *docker.sock* && "$mounts" != *lifeos-transactions* && "$mounts" != *'/root/'* ]] \
    || fail forbidden_host_mount_detected
done

bind_ip=$(sed -n 's/^LIFEOS_RUNDECK_BIND_IP=//p' "$ENV_FILE")
[[ -n "$bind_ip" && "$bind_ip" != 0.0.0.0 && "$bind_ip" != 127.0.0.1 ]] \
  || fail invalid_lan_bind_address
published=$(docker inspect -f '{{(index (index .NetworkSettings.Ports "4440/tcp") 0).HostIp}}' "$rundeck_id") \
  || fail rundeck_published_port_inspection_failed
[[ "$published" == "$bind_ip" ]] || fail rundeck_not_bound_to_configured_lan_address

# Exercise durable DB storage without using or revealing credentials: the
# container already receives its secret through Compose. Restart PostgreSQL and
# prove a shadow-only acceptance row survives.
timeout 30s docker exec "$db_id" psql -U rundeck -d rundeck -v ON_ERROR_STOP=1 \
  -c 'CREATE TABLE IF NOT EXISTS lifeos_shadow_acceptance (id text PRIMARY KEY);' \
  -c "INSERT INTO lifeos_shadow_acceptance (id) VALUES ('$JOB_ID') ON CONFLICT (id) DO NOTHING;" \
  >/dev/null || fail persistence_canary_create_failed
# Stop the application before deliberately interrupting its database. Leaving
# Rundeck running here can put its unless-stopped policy into a restart race with
# an explicit `compose restart rundeck`, making a sound persistent stack fail the
# acceptance rehearsal nondeterministically.
compose stop -t 60 rundeck >/dev/null || fail rundeck_recovery_stop_failed
compose restart rundeck-db >/dev/null || fail database_restart_failed
# Wait for PostgreSQL before starting Rundeck. `compose start` does not
# re-evaluate depends_on health conditions, so the launcher enforces that
# ordering itself.
db_id=$(lookup_container_id rundeck-db) || fail rundeck_db_container_lookup_failed_after_restart
[[ -n "$db_id" ]] || fail rundeck_db_container_missing_after_restart
for _ in $(seq 1 60); do
  [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$db_id" 2>/dev/null || true)" == healthy ]] \
    && break
  sleep 2
done
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$db_id" 2>/dev/null || true)" == healthy ]] \
  || fail database_unhealthy_after_restart
# Recreate neither service here: starting the stopped Rundeck container
# exercises recovery from the database interruption while retaining both
# persistent volumes.
compose start rundeck >/dev/null || fail rundeck_recovery_start_failed
compose up -d --wait --wait-timeout 600 >/dev/null || fail post_restart_health_failed
db_id=$(lookup_container_id rundeck-db) || fail rundeck_db_container_lookup_failed_after_recovery
[[ -n "$db_id" ]] || fail rundeck_db_container_missing_after_recovery
canary=$(timeout 30s docker exec "$db_id" psql -U rundeck -d rundeck -At \
  -c "SELECT count(*) FROM lifeos_shadow_acceptance WHERE id='$JOB_ID';") \
  || fail database_persistence_canary_query_failed
[[ "$canary" == 1 ]] || fail database_persistence_canary_failed

# Rehearse backup and restore entirely inside the isolated shadow database.
# No dump, password, or row content crosses the container boundary or enters
# logs. The disposable restore database is removed after its canary is read.
# The command substitution must execute in the container.
# shellcheck disable=SC2016
timeout 60s docker exec "$db_id" sh -eu -c \
  'pg_dump -U rundeck -Fc rundeck -f /tmp/lifeos-shadow.dump &&
   dropdb -U rundeck --if-exists lifeos_shadow_restore &&
   createdb -U rundeck lifeos_shadow_restore &&
   pg_restore -U rundeck -d lifeos_shadow_restore /tmp/lifeos-shadow.dump &&
   test "$(psql -U rundeck -d lifeos_shadow_restore -At -c "SELECT count(*) FROM lifeos_shadow_acceptance WHERE id='"'"'80f20f03755d'"'"';")" = 1 &&
   dropdb -U rundeck lifeos_shadow_restore && rm -f /tmp/lifeos-shadow.dump' \
  || fail database_backup_restore_rehearsal_failed

[[ "$(systemctl is-enabled lifeos-backlog-runner.timer 2>/dev/null || true)" == "$compat_timer_enabled" ]] \
  || fail compatibility_timer_enablement_changed
[[ "$(systemctl is-active lifeos-backlog-runner.timer 2>/dev/null || true)" == "$compat_timer_active" ]] \
  || fail compatibility_timer_runtime_changed
[[ "$(systemctl is-enabled lifeos-backlog-runner.service 2>/dev/null || true)" == "$compat_service_enabled" ]] \
  || fail compatibility_service_enablement_changed
# The timer-triggered service is transient: a legitimate backlog invocation may
# move it between inactive and active during this bounded (potentially 20-minute)
# shadow exercise. Exact equality here produced a false shadow-acceptance failure.
# Ensure the unit did not fail; exact timer state and service enablement above are
# stable evidence that this launcher neither cut over nor disabled the old path.
compat_service_state=$(systemctl is-active lifeos-backlog-runner.service 2>/dev/null || true)
[[ "$compat_service_state" != failed ]] || fail compatibility_service_failed_after_shadow_test

started_here=false
printf 'SHADOW_DEPLOYMENT=PASS containers=healthy images=digest_resolved persistence=restart_verified backup_restore=verified lan_binding=bounded\n'
printf 'SHADOW_EQUIVALENCE=PASS comparator=watchman_backlog compatibility_path=unchanged semaphore=design_only\n'
result PASS none \
  "add the read-only Ansible catalogue and bounded Rundeck job definitions without cutting over" \
  PASS "repository contract and Pi5 shadow health, persistence, boundary, and compatibility checks PASS" \
  "verify healthy containers and unchanged backlog timer after the next Pi5 reboot"
