#!/usr/bin/env bash
set -uo pipefail
# LifeOS serial purge gate harness.
# A gate failure is evidence, not a reason to abandon independent later gates.
# Exit is non-zero only after every runnable gate has been attempted.
ARTIFACT_DIR="${LIFEOS_GATE_ARTIFACT_DIR:-/tmp/lifeos-ots-purge-gates}"
mkdir -p "$ARTIFACT_DIR"
summary="$ARTIFACT_DIR/summary.tsv"
: >"$summary"
failures=0
blocked=0

gate() {
  local id="$1" name="$2" deps="$3"; shift 3
  local log="$ARTIFACT_DIR/${id}.log"
  if [[ -n "$deps" ]]; then
    local dep
    IFS=',' read -ra ds <<<"$deps"
    for dep in "${ds[@]}"; do
      if ! grep -q "^$dep"$'\t'"PASS"$'\t' "$summary"; then
        printf '%s\tBLOCKED\t%s\tdependency=%s\n' "$id" "$name" "$dep" | tee -a "$summary"
        blocked=$((blocked+1)); return 0
      fi
    done
  fi
  echo "================================================================"
  echo "GATE_ID=$id"
  echo "GATE_NAME=$name"
  echo "GATE_DEPENDENCIES=${deps:-none}"
  echo "GATE_STARTED_AT=$(date --iso-8601=seconds)"
  echo "GATE_COMMAND=$*"
  echo "GATE_STATUS=RUNNING"
  echo "================================================================"
  set +e
  "$@" > >(tee "$log") 2>&1
  rc=$?
  set -e
  if (( rc == 0 )); then
    echo "GATE_RESULT=PASS"
    echo "GATE_FINISHED_AT=$(date --iso-8601=seconds)"
    echo "GATE_LOG=$log"
    printf '%s\tPASS\t%s\t%s\n' "$id" "$name" "$log" | tee -a "$summary"
  else
    echo "GATE_RESULT=FAIL"
    echo "GATE_RETURN_CODE=$rc"
    echo "GATE_FINISHED_AT=$(date --iso-8601=seconds)"
    echo "GATE_LOG=$log"
    echo "GATE_CONTINUATION=YES"
    printf '%s\tFAIL\t%s\trc=%s log=%s\n' "$id" "$name" "$rc" "$log" | tee -a "$summary"
    failures=$((failures+1))
  fi
  return 0
}

set -e
# 801-01 was already live-proven in Actions run 35536667941. Re-audit it
# independently here so this harness never trusts a historical green tick.
echo "BATCH_PHASE=801_CONSUMER_REAUDIT"
echo "BATCH_RUNNER_REVISION=2"
echo "BATCH_POLICY=failure_is_logged_then_continue"
echo "BATCH_STARTED_AT=$(date --iso-8601=seconds)"
echo "BATCH_ARTIFACT_DIR=$ARTIFACT_DIR"
echo "BATCH_GATE_COUNT=8"

gate 801-01 "HA bridge legacy-state removal" "" bash -c '
  ! grep -q "/var/lib/lifeos-backlog-runner/state.json" governor/ha_issue_queue_bridge.py &&
  ! grep -q "/var/lib/lifeos-backlog-runner/state.json" governor/systemd/lifeos-ha-issue-queue-bridge.service &&
  test "$(systemctl is-active lifeos-ha-issue-queue-bridge.service)" = active &&
  cmp -s governor/ha_issue_queue_bridge.py /usr/local/libexec/lifeos-ha-issue-queue-bridge &&
  journalctl -u lifeos-ha-issue-queue-bridge.service --since "-90 seconds" --no-pager | grep -q "QUEUE_REFRESH=PASS"
'

gate 801-02 "terminal observer uses Governor plus GitHub" "" bash -c '
  ! grep -q "/var/lib/lifeos-backlog-runner/state.json" scripts/lifeos-semaphore-terminal-observer.sh &&
  TIMEOUT_SECONDS=60 POLL_SECONDS=2 bash scripts/lifeos-semaphore-terminal-observer.sh 11618ff914ce 28
'

# Remaining references are classified without stopping the batch. Active
# migration/proof scripts fail this gate; immutable runtime-job/archive evidence
# is reported but does not count as an active dependency.
gate 801-03 "no active script depends on retired backlog state" "" bash -c '
  refs=$(grep -RIl --exclude-dir=.git --exclude=lifeos-ots-purge-gated-runner.sh "/var/lib/lifeos-backlog-runner/state.json" scripts governor 2>/dev/null || true)
  active=$(printf "%s\n" "$refs" | grep -v "^governor/runtime_jobs/" | grep -v "^archive/" || true)
  printf "ALL_REFS=%s\n" "$refs"
  printf "ACTIVE_REFS=%s\n" "$active"
  test -z "$active"
'

gate 801-04 "retired backlog deploy capability absent" "" bash -c '
  ! grep -q "deploy-backlog-runner" governor/autonomous_agent.py &&
  ! grep -q "deploy-backlog-runner" homelab/live/usr/local/sbin/lifeos-root-broker &&
  python -m pytest -q tests/test_bounded_deployment_broker.py tests/test_privileged_target_identity.py
'

gate 801-05 "obsolete backlog-runner migration proofs absent" "" bash -c '
  stale=(
    scripts/lifeos-semaphore-dispatch-fixture-proof.sh
    scripts/lifeos-semaphore-replacement-scope-audit.sh
    scripts/lifeos-semaphore-shadow-audit.sh
    tests/test_backlog_runner.py
  )
  for path in "${stale[@]}"; do
    if test -e "$path"; then
      echo "STALE_MIGRATION_ASSET=$path"
      exit 1
    fi
  done
  refs=$(grep -RIl --exclude-dir=.git --exclude-dir=archive --exclude-dir=runtime_jobs --exclude=lifeos-ots-purge-gated-runner.sh -E "governor/backlog_runner.py|install-backlog-runner-pi5.sh" . 2>/dev/null || true)
  printf "ACTIVE_RETIRED_BACKLOG_CODE_REFS=%s\\n" "$refs"
  test -z "$refs"
'


gate 801-06 "active runtime source has no retired backlog-runner references" "" bash -c '
  refs=$(grep -RIl --exclude-dir=.git --exclude-dir=archive --exclude-dir=runtime_jobs --exclude=lifeos-ots-purge-gated-runner.sh --exclude=lifeos-semaphore-terminal-observer.sh -E "lifeos-backlog-runner|governor/backlog_runner.py|install-backlog-runner-pi5.sh|design_shadow_adapter_for_backlog_runner_replacement" governor scripts homelab orchestration 2>/dev/null || true)
  printf "ACTIVE_RUNTIME_RETIRED_BACKLOG_REFS=%s\\n" "$refs"
  test -z "$refs"
'


gate 801-06b "retired backlog runtime artifacts inventory" "" bash -c '
  echo "RUNTIME_ARTIFACT_AUDIT=START"
  state=/var/lib/lifeos-backlog-runner/state.json
  dropin=/etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf
  for p in "$state" "$dropin"; do
    if test -e "$p"; then
      echo "RETIRED_RUNTIME_ARTIFACT=PRESENT path=$p"
    else
      echo "RETIRED_RUNTIME_ARTIFACT=ABSENT path=$p"
    fi
  done
  systemctl show lifeos-autonomous-agent.service -p DropInPaths -p ActiveState -p SubState --no-pager || true
  echo "RUNTIME_ARTIFACT_AUDIT=PASS"
'

gate 801-07 "retired backlog runtime artifacts absent" "801-06b" bash -c '
  state=/var/lib/lifeos-backlog-runner/state.json
  dropin=/etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf
  if test -e "$state"; then echo "RETIRED_BACKLOG_STATE=PRESENT"; exit 1; fi
  if test -e "$dropin"; then echo "RETIRED_BACKLOG_DROPIN=PRESENT"; exit 1; fi
  if systemctl show lifeos-autonomous-agent.service -p DropInPaths --value | grep -q "backlog-dispatcher.conf"; then
    echo "RETIRED_BACKLOG_DROPIN=LOADED"; exit 1
  fi
  echo "RETIRED_BACKLOG_STATE=ABSENT"
  echo "RETIRED_BACKLOG_DROPIN=ABSENT"
'


gate 801-08 "installed gateway aligned and retired cleanup capability rejected" "" bash -c '
  cmp -s homelab/live/usr/local/sbin/lifeos-deploy-gateway /usr/local/sbin/lifeos-deploy-gateway || {
    echo "INSTALLED_GATEWAY_ALIGNMENT=FAIL"; exit 1;
  }
  echo "INSTALLED_GATEWAY_ALIGNMENT=PASS"
  set +e
  out=$(sudo -n /usr/local/sbin/lifeos-deploy-gateway cleanup-retired-backlog-runtime 2>&1)
  rc=$?
  set -e
  printf "%s\n" "$out"
  test "$rc" -eq 64 || { echo "RETIRED_CLEANUP_CAPABILITY_REJECTION=FAIL rc=$rc"; exit 1; }
  echo "RETIRED_CLEANUP_CAPABILITY_REJECTION=PASS"
'

echo "================================================================"
echo "BATCH_PHASE=CONSOLIDATED_REPORT"
echo "BATCH_FINISHED_AT=$(date --iso-8601=seconds)"
echo "=== CONSOLIDATED GATE REPORT ==="
cat "$summary"
echo "GATE_FAILURES=$failures"
echo "GATE_BLOCKED=$blocked"
if (( failures || blocked )); then
  echo "FINAL_ACCEPTANCE=FAIL"
  exit 1
fi
echo "FINAL_ACCEPTANCE=PASS"
