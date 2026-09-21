#!/usr/bin/env bash
set -Eeuo pipefail

VERSION=1
STAMP="$(date +%Y%m%d-%H%M%S)"
ROOT="/var/lib/lifeos-stage9-rehearsal"
WORK="$ROOT/$STAMP"
TARGET="$WORK/managed-state.env"
BACKUP="$WORK/managed-state.env.before"
PROTECTED=(
  lifeos-control-job-submit.socket
  lifeos-root-broker.socket
  lifeos-autonomous-agent.service
  lifeos-engineer.service
  lifeos-ha-issue-queue-bridge.service
)

fail(){ echo "RESULT=FAIL"; echo "BARRIER=$1"; exit 1; }
state(){ systemctl is-active "$1" 2>/dev/null || true; }

[[ $EUID -eq 0 ]] || fail must_run_as_root
install -d -o root -g root -m 0750 "$WORK"

printf 'STAGE9_ROLLBACK_REHEARSAL_VERSION=%s\n' "$VERSION"
printf 'MUTATIONS=SCRATCH_STATE_ONLY\n'
printf 'SCRATCH=%s\n' "$WORK"

# Snapshot protected unit state. No unit is restarted or modified by this rehearsal.
declare -A BEFORE
for u in "${PROTECTED[@]}"; do
  BEFORE["$u"]="$(state "$u")"
  printf 'PROTECTED_BEFORE=%s:%s\n' "$u" "${BEFORE[$u]}"
done

# Establish known-good scratch state and preserve it byte-for-byte.
printf 'schema=1\nmode=healthy\nvalue=canonical\n' > "$TARGET"
cp -a "$TARGET" "$BACKUP"
ORIGINAL_SHA="$(sha256sum "$TARGET" | awk '{print $1}')"
printf 'ORIGINAL_SHA256=%s\n' "$ORIGINAL_SHA"

# Candidate deployment deliberately violates the synthetic health contract.
printf 'schema=1\nmode=broken\nvalue=candidate\n' > "$TARGET"
CANDIDATE_SHA="$(sha256sum "$TARGET" | awk '{print $1}')"
printf 'CANDIDATE_SHA256=%s\n' "$CANDIDATE_SHA"
[[ "$CANDIDATE_SHA" != "$ORIGINAL_SHA" ]] || fail candidate_did_not_change

# Synthetic health gate: only mode=healthy is accepted. The bad candidate MUST fail.
if grep -qx 'mode=healthy' "$TARGET"; then
  fail synthetic_bad_candidate_was_accepted
fi
echo 'FAILED_DEPLOYMENT_DETECTED=PASS'

# Automatic rollback to the exact previous state.
install -o root -g root -m 0640 "$BACKUP" "$TARGET"
RESTORED_SHA="$(sha256sum "$TARGET" | awk '{print $1}')"
printf 'RESTORED_SHA256=%s\n' "$RESTORED_SHA"
[[ "$RESTORED_SHA" == "$ORIGINAL_SHA" ]] || fail rollback_identity_mismatch
grep -qx 'mode=healthy' "$TARGET" || fail rollback_health_gate_failed
echo 'AUTOMATIC_ROLLBACK=PASS'
echo 'ROLLBACK_IDENTITY=PASS'

# Re-prove that protected services were untouched throughout the exercise.
for u in "${PROTECTED[@]}"; do
  after="$(state "$u")"
  printf 'PROTECTED_AFTER=%s:%s\n' "$u" "$after"
  [[ "$after" == "${BEFORE[$u]}" ]] || fail "protected_unit_changed_${u}"
  [[ "$after" == active ]] || fail "protected_unit_not_active_${u}"
done

echo 'PROTECTED_SERVICES_UNCHANGED=PASS'
echo 'LIVE_HOME_ASSISTANT_MUTATION=NONE'
echo 'LIVE_SEMAPHORE_MUTATION=NONE'
echo 'LIVE_GITHUB_STATE_MUTATION=NONE'
echo 'RESULT=PASS'
echo 'STAGE9_FAILED_DEPLOYMENT_ROLLBACK_PROOF=PASS'
echo 'NEXT_ACTION=prove bounded service failure detection and recovery'
