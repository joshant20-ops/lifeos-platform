#!/usr/bin/env bash
set -euo pipefail

PLATFORM=/home/joshan/lifeos-platform
cd "$PLATFORM"

printf '%s\n' 'STAGE9_EXIT_GATE_AUDIT_VERSION=1'
printf '%s\n' 'MUTATIONS=BOUNDED_PROOF_REHEARSALS_ONLY'
printf 'PLATFORM_HEAD=%s\n' "$(git rev-parse HEAD)"

fail() {
  printf 'STAGE9_EXIT_GATE=BLOCKED\nBLOCKER=%s\nRESULT=RETRY\n' "$1"
  exit 1
}

printf '\n=== 1/8 REPOSITORY IDENTITY ===\n'
head_sha=$(git rev-parse HEAD)
origin_sha=$(git rev-parse origin/main)
[[ "$head_sha" == "$origin_sha" ]] || fail repository_not_at_origin_main
[[ -z "$(git status --porcelain)" ]] || fail repository_dirty
printf 'REPOSITORY_IDENTITY=PASS\n'

printf '\n=== 2/8 COMPOSE INVENTORY ===\n'
python3 scripts/validate-compose-inventory.py | tee /tmp/lifeos-stage9-compose.out
grep -q '^COMPOSE_INVENTORY=PASS$' /tmp/lifeos-stage9-compose.out || fail compose_inventory
printf 'COMPOSE_GATE=PASS\n'

printf '\n=== 3/8 RUNNING IMAGE IDENTITY ===\n'
python3 scripts/lifeos-running-image-digest-audit.py | tee /tmp/lifeos-stage9-digest.out
grep -q '^RUNNING_IMAGE_DIGEST_AUDIT=PASS$' /tmp/lifeos-stage9-digest.out || fail running_image_digest
if grep -Eq '^DRIFT=[1-9][0-9]*$' /tmp/lifeos-stage9-digest.out; then fail running_image_drift; fi
printf 'IMAGE_IDENTITY_GATE=PASS\n'

printf '\n=== 4/8 CORE CONTROL PLANE ===\n'
protected=(
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
  lifeos-ha-issue-queue-bridge.service
)
for unit in "${protected[@]}"; do
  state=$(systemctl is-active "$unit" 2>/dev/null || true)
  printf 'PROTECTED=%s:%s\n' "$unit" "$state"
  [[ "$state" == active ]] || fail "protected_unit_${unit}_$state"
done
runner=$(systemctl list-units --type=service --all --no-legend | awk '$1 ~ /^actions\.runner\.joshant20-ops-lifeos-platform\.lifeos-pi5\.service$/ {print $1; exit}')
[[ -n "$runner" ]] || fail github_runner_service_missing
[[ "$(systemctl is-active "$runner" 2>/dev/null || true)" == active ]] || fail github_runner_inactive
printf 'GITHUB_RUNNER=PASS service=%s\n' "$runner"

docker inspect lifeos-semaphore-shadow-semaphore-db-1 >/dev/null 2>&1 || fail semaphore_db_missing
[[ "$(docker inspect -f '{{.State.Status}}' lifeos-semaphore-shadow-semaphore-db-1)" == running ]] || fail semaphore_db_not_running
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' lifeos-semaphore-shadow-semaphore-db-1)" == healthy ]] || fail semaphore_db_unhealthy
[[ "$(docker inspect -f '{{.State.Status}}' lifeos-semaphore-shadow-semaphore-1 2>/dev/null || true)" == running ]] || fail semaphore_not_running
if ! curl -fsS --max-time 5 http://192.168.0.203:3000/api/ping >/dev/null; then fail semaphore_api_unreachable; fi
printf 'SEMAPHORE_GATE=PASS\n'

printf '\n=== 5/8 HOME ASSISTANT / ENERGY REFERENCES ===\n'
bash scripts/lifeos-ha-energy-entity-audit.sh | tee /tmp/lifeos-stage9-energy.out
grep -q '^AUDIT_RESULT=PASS$' /tmp/lifeos-stage9-energy.out || fail ha_energy_entity_audit
printf 'HOME_ASSISTANT_REFERENCE_GATE=PASS\n'

printf '\n=== 6/8 FAILED DEPLOYMENT + ROLLBACK PROOF ===\n'
sudo -E bash scripts/lifeos-stage9-rollback-rehearsal.sh | tee /tmp/lifeos-stage9-rollback.out
grep -q '^STAGE9_FAILED_DEPLOYMENT_ROLLBACK_PROOF=PASS$' /tmp/lifeos-stage9-rollback.out || fail failed_deployment_rollback_proof
printf 'FAILED_DEPLOYMENT_ROLLBACK_GATE=PASS\n'

printf '\n=== 7/8 BOUNDED SERVICE FAILURE + RECOVERY PROOF ===\n'
sudo -E bash scripts/lifeos-stage9-service-recovery-rehearsal.sh | tee /tmp/lifeos-stage9-recovery.out
grep -q '^STAGE9_BOUNDED_SERVICE_FAILURE_RECOVERY_PROOF=PASS$' /tmp/lifeos-stage9-recovery.out || fail service_recovery_proof
printf 'SERVICE_RECOVERY_GATE=PASS\n'

printf '\n=== 8/8 FINAL INVARIANTS ===\n'
for unit in "${protected[@]}"; do
  [[ "$(systemctl is-active "$unit" 2>/dev/null || true)" == active ]] || fail "final_protected_unit_${unit}"
done
[[ "$(systemctl is-active "$runner" 2>/dev/null || true)" == active ]] || fail final_github_runner
[[ "$(docker inspect -f '{{.State.Status}}' homeassistant 2>/dev/null || true)" == running ]] || fail final_homeassistant_not_running
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' homeassistant 2>/dev/null || true)" == healthy ]] || fail final_homeassistant_not_healthy
if ! curl -fsS --max-time 5 http://192.168.0.203:3000/api/ping >/dev/null; then fail final_semaphore_api; fi
printf 'FINAL_INVARIANTS=PASS\n'

printf '\nRESULT=PASS\n'
printf 'STAGE9_EXIT_GATE=PASS\n'
printf 'NORMAL_PLATFORM_HEALTH=PASS\n'
printf 'FAILED_DEPLOYMENT_ROLLBACK=PROVEN\n'
printf 'BOUNDED_SERVICE_RECOVERY=PROVEN\n'
printf 'PROTECTED_CONTROL_PLANE=PASS\n'
printf 'GITHUB_RUNNER=PASS\n'
printf 'SEMAPHORE=PASS\n'
printf 'HOME_ASSISTANT=PASS\n'
printf 'NEXT_ACTION=begin Stage 10 autonomous engineering pipeline build\n'
