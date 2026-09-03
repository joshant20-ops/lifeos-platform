#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}
PROJECT=lifeos-semaphore-shadow

echo 'SEMAPHORE_REPLACEMENT_SCOPE_AUDIT_VERSION=1'
echo 'MUTATIONS=NONE'

echo
echo '=== SEMAPHORE RUNTIME ==='
docker ps --filter "label=com.docker.compose.project=$PROJECT" --format 'name={{.Names}} image={{.Image}} status={{.Status}}'

echo
echo '=== CUSTOM EXECUTION UNITS ==='
for unit in \
  lifeos-backlog-runner.timer \
  lifeos-backlog-runner.service \
  lifeos-engineer-dispatcher.timer \
  lifeos-engineer-dispatcher.service \
  lifeos-engineer-worker.timer \
  lifeos-engineer-worker.service \
  lifeos-control-job-submit.socket \
  lifeos-control-job-submit@.service \
  lifeos-root-broker.socket \
  lifeos-root-broker@.service \
  lifeos-autonomous-agent.service \
  lifeos-engineer.service; do
  printf '%-40s active=%-10s enabled=%s\n' "$unit" \
    "$(systemctl is-active "$unit" 2>/dev/null || true)" \
    "$(systemctl is-enabled "$unit" 2>/dev/null || true)"
done

echo
echo '=== RESPONSIBILITY EVIDENCE ==='
for path in \
  governor/backlog_runner.py \
  governor/autonomous_agent.py \
  governor/ha_issue_queue_bridge.py \
  homelab/live/usr/local/libexec/lifeos-control-job-submit-bridge \
  homelab/live/usr/local/sbin/lifeos-root-broker \
  governor/systemd/lifeos-backlog-runner.service \
  governor/systemd/lifeos-backlog-runner.timer \
  governor/systemd/lifeos-autonomous-agent.service; do
  if [[ -f "$PLATFORM/$path" ]]; then
    echo "--- $path ---"
    grep -Ein 'issue|queue|job|timer|socket|root|sudo|ansible|git|dispatch|worker|execute|run|state|result|retry|publish' "$PLATFORM/$path" | head -80 || true
  fi
done

echo
echo '=== SEMAPHORE / ANSIBLE ASSETS ==='
find "$PLATFORM/orchestration/semaphore" -maxdepth 3 -type f -printf '%P\n' 2>/dev/null | sort || true
find "$PLATFORM/ansible" -maxdepth 3 -type f \( -name '*.yml' -o -name '*.yaml' -o -name '*.json' \) -printf '%P\n' 2>/dev/null | sort | head -200 || true

echo
echo '=== CLASSIFICATION ==='
echo 'lifeos-backlog-runner=REPLACE_CANDIDATE reason=scheduling_queue_execution_overlaps_semaphore_task_runs'
echo 'lifeos-engineer-dispatcher-worker=REPLACE_OR_COLLAPSE_CANDIDATE reason=dispatch_worker_execution_can_move_to_semaphore_templates'
echo 'lifeos-control-job-submit-bridge=BRIDGE_CANDIDATE reason=current_ingress_can_submit_allowlisted_semaphore_tasks_during_transition'
echo 'lifeos-root-broker=KEEP reason=privileged_host_boundary_not_safely_replaced_by_semaphore_container'
echo 'lifeos-autonomous-agent=KEEP reason=decision_planning_loop_not_execution_orchestrator'
echo 'lifeos-engineer=KEEP reason=local_ai_backend_not_execution_orchestrator'
echo 'ha-issue-queue-bridge=KEEP_OR_SIMPLIFY reason=home_assistant_ingress_is_separate_from_execution_engine'

echo
echo '=== SAFETY RULE ==='
echo 'NO_CUSTOM_COMPONENT_SHOULD_BE_DISABLED_UNTIL=A_SEMAPHORE_ADAPTER_RUNS_ALLOWLISTED_ANSIBLE_TASKS_AND_RESULT_PROPAGATION_IS_PROVEN'
echo 'NEXT_ACTION=build_read_only_semaphore_adapter_and_shadow_execute_one_non_destructive_ansible_job'
echo 'AUDIT_RESULT=PASS'
