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
  echo "=== GATE $id START: $name ==="
  set +e
  "$@" > >(tee "$log") 2>&1
  rc=$?
  set -e
  if (( rc == 0 )); then
    printf '%s\tPASS\t%s\t%s\n' "$id" "$name" "$log" | tee -a "$summary"
  else
    printf '%s\tFAIL\t%s\trc=%s log=%s\n' "$id" "$name" "$rc" "$log" | tee -a "$summary"
    failures=$((failures+1))
  fi
  return 0
}

set -e
# 801-01 was already live-proven in Actions run 35536667941. Re-audit it
# independently here so this harness never trusts a historical green tick.
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
  refs=$(grep -RIl --exclude-dir=.git "/var/lib/lifeos-backlog-runner/state.json" scripts governor 2>/dev/null || true)
  active=$(printf "%s\n" "$refs" | grep -v "^governor/runtime_jobs/" | grep -v "^archive/" || true)
  printf "ALL_REFS=%s\n" "$refs"
  printf "ACTIVE_REFS=%s\n" "$active"
  test -z "$active"
'

echo "=== CONSOLIDATED GATE REPORT ==="
cat "$summary"
echo "GATE_FAILURES=$failures"
echo "GATE_BLOCKED=$blocked"
if (( failures || blocked )); then
  echo "FINAL_ACCEPTANCE=FAIL"
  exit 1
fi
echo "FINAL_ACCEPTANCE=PASS"
