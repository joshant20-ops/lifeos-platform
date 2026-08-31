#!/usr/bin/env bash
set -euo pipefail

# Keep the deployment and Home Assistant transaction in one maintained runtime
# implementation while attributing the emitted PASS/FAIL evidence to this job.
readonly JOB_ID=e589eb65fbbc
readonly REPO=/home/joshan/lifeos-platform
readonly RUNTIME="$REPO/governor/runtime_jobs/ebf8a71d4bff.sh"
# The delegated runtime can legitimately consume 900s deploying Open WebUI,
# then up to 870s checking and restarting Home Assistant. Keep this
# guard above that nested budget, and allow a signal-triggered HA rollback to
# finish before timeout escalates from TERM to KILL.
readonly OUTER_TIMEOUT_SECONDS=1800
readonly ROLLBACK_GRACE_SECONDS=360

if [[ "$(hostname)" != Docker ]]; then
  printf 'RESULT=FAIL job=%s reason=must_run_on_pi5_Docker\n' "$JOB_ID"
  exit 20
fi
if [[ ! -x "$RUNTIME" ]]; then
  printf 'RESULT=FAIL job=%s reason=engineer_runtime_implementation_missing path=%s\n' "$JOB_ID" "$RUNTIME"
  exit 21
fi

printf 'RUNTIME_CHECK=START job=%s scope=engineer_deployment_and_home_assistant\n' "$JOB_ID"
if timeout --signal=TERM --kill-after="${ROLLBACK_GRACE_SECONDS}s" "$OUTER_TIMEOUT_SECONDS" \
  env LIFEOS_RUNTIME_JOB_ID="$JOB_ID" "$RUNTIME"; then
  printf 'RUNTIME_CHECK=PASS job=%s\n' "$JOB_ID"
  exit 0
else
  status=$?
fi

if [[ "$status" -eq 124 || "$status" -eq 137 ]]; then
  printf 'RESULT=FAIL job=%s reason=runtime_timeout timeout=%ss\n' "$JOB_ID" "$OUTER_TIMEOUT_SECONDS"
else
  printf 'RESULT=FAIL job=%s reason=runtime_verification_failed exit=%s\n' "$JOB_ID" "$status"
fi
exit "$status"
