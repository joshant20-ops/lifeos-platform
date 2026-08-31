#!/usr/bin/env bash
set -euo pipefail

# Attribute the maintained Engineer deployment and transactional Home Assistant
# verification to this autonomous job. The implementation owns all mutation,
# rollback, and failure diagnostics; this launcher only supplies a safe outer
# deadline with enough grace for rollback after TERM.
readonly JOB_ID=feb1efaecf51
readonly REPO=/home/joshan/lifeos-platform
readonly RUNTIME="$REPO/governor/runtime_jobs/ebf8a71d4bff.sh"
readonly OUTER_TIMEOUT_SECONDS=2700
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
  printf 'RUNTIME_CHECK=PASS job=%s checks=backend_/health,openwebui_/health,healthy_container_reuse,home_assistant_panel\n' "$JOB_ID"
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
