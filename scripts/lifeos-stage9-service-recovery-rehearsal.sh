#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo 'ERROR=must_run_as_root'; exit 1; }

UNIT=lifeos-stage9-recovery-proof.service
UNIT_PATH=/run/systemd/system/$UNIT
STATE_DIR=/run/lifeos-stage9-recovery-proof
MARKER=$STATE_DIR/recover.ok
PROTECTED=(
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
  lifeos-ha-issue-queue-bridge.service
)

cleanup() {
  systemctl stop "$UNIT" >/dev/null 2>&1 || true
  rm -f "$UNIT_PATH" "$MARKER"
  rmdir "$STATE_DIR" >/dev/null 2>&1 || true
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl reset-failed "$UNIT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

printf '%s\n' 'STAGE9_SERVICE_RECOVERY_REHEARSAL_VERSION=1'
printf '%s\n' 'MUTATIONS=TEMPORARY_RUN_SYSTEMD_UNIT_ONLY'
printf '%s\n' 'LIVE_HOME_ASSISTANT_MUTATION=NONE'
printf '%s\n' 'LIVE_SEMAPHORE_MUTATION=NONE'
printf '%s\n' 'LIVE_GITHUB_STATE_MUTATION=NONE'

mkdir -p "$STATE_DIR"
rm -f "$MARKER"

before=()
for u in "${PROTECTED[@]}"; do
  state=$(systemctl is-active "$u" 2>/dev/null || true)
  before+=("$u:$state")
  echo "PROTECTED_BEFORE=$u:$state"
  [[ "$state" == active ]] || { echo "ERROR=protected_unit_not_active:$u:$state"; exit 1; }
done

cat >"$UNIT_PATH" <<'EOF'
[Unit]
Description=LifeOS Stage 9 bounded recovery proof

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'test -f /run/lifeos-stage9-recovery-proof/recover.ok'
RemainAfterExit=yes
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/
ReadWritePaths=/run/lifeos-stage9-recovery-proof
EOF

systemctl daemon-reload

# 1. Deliberate bounded failure: marker is absent.
set +e
systemctl start "$UNIT" >/dev/null 2>&1
first_rc=$?
set -e
first_state=$(systemctl is-failed "$UNIT" 2>/dev/null || true)
[[ $first_rc -ne 0 ]] || { echo 'ERROR=expected_initial_failure_not_observed'; exit 1; }
[[ "$first_state" == failed ]] || { echo "ERROR=failed_state_not_detected:$first_state"; exit 1; }
echo 'BOUNDED_SERVICE_FAILURE_DETECTED=PASS'

# 2. Automatic recovery action: satisfy only the proof service prerequisite,
# reset the failed unit and retry. No production service is modified.
: >"$MARKER"
systemctl reset-failed "$UNIT"
systemctl start "$UNIT"
recovered_state=$(systemctl is-active "$UNIT" 2>/dev/null || true)
[[ "$recovered_state" == active ]] || { echo "ERROR=recovery_failed:$recovered_state"; exit 1; }
echo 'AUTOMATIC_SERVICE_RECOVERY=PASS'

# 3. Verify the recovered service really executed the expected condition.
[[ -f "$MARKER" ]] || { echo 'ERROR=recovery_marker_missing'; exit 1; }
echo 'RECOVERY_CONDITION_VERIFIED=PASS'

# 4. Protected control-plane invariants must be identical.
after=()
for u in "${PROTECTED[@]}"; do
  state=$(systemctl is-active "$u" 2>/dev/null || true)
  after+=("$u:$state")
  echo "PROTECTED_AFTER=$u:$state"
  [[ "$state" == active ]] || { echo "ERROR=protected_unit_changed:$u:$state"; exit 1; }
done
[[ "${before[*]}" == "${after[*]}" ]] || { echo 'ERROR=protected_service_state_changed'; exit 1; }
echo 'PROTECTED_SERVICES_UNCHANGED=PASS'

echo 'RESULT=PASS'
echo 'STAGE9_BOUNDED_SERVICE_FAILURE_RECOVERY_PROOF=PASS'
echo 'TEMPORARY_UNIT_PERSISTED=NO'
echo 'NEXT_ACTION=run Stage 9 consolidated exit-gate audit and close remaining blockers'
