#!/usr/bin/env bash
set -euo pipefail

# The original goal runtime owns the reversible Home Assistant transaction.
# This job-specific launcher adds the requested fixed-address verification and
# keeps a single maintained implementation for backup, config validation,
# restart, rollback, and sidebar-route checks.
readonly JOB_ID=86cdbb0999a1
readonly REPO=/home/joshan/lifeos-platform
readonly RUNTIME="$REPO/governor/runtime_jobs/feb1efaecf51.sh"
readonly ENGINEER_URL=http://192.168.0.203:8792/
readonly OUTER_TIMEOUT_SECONDS=2700
readonly ROLLBACK_GRACE_SECONDS=360

fail() {
  local reason=${1:-unknown_failure}
  local status=${2:-1}
  printf 'RESULT=FAIL job=%s reason=%s\n' "$JOB_ID" "$reason"
  exit "$status"
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker 20
[[ -x "$RUNTIME" ]] || fail engineer_runtime_implementation_missing 21

printf 'RUNTIME_CHECK=START job=%s scope=engineer_home_assistant_sidebar\n' "$JOB_ID"
if timeout --signal=TERM --kill-after="${ROLLBACK_GRACE_SECONDS}s" \
  "$OUTER_TIMEOUT_SECONDS" env LIFEOS_RUNTIME_JOB_ID="$JOB_ID" "$RUNTIME"; then
  :
else
  status=$?
  if [[ "$status" -eq 124 || "$status" -eq 137 ]]; then
    fail "runtime_timeout_${OUTER_TIMEOUT_SECONDS}s" "$status"
  fi
  fail "runtime_verification_failed_exit_${status}" "$status"
fi

# Confirm the exact address requested by the goal after deployment and HA
# integration have completed. Headers only: no private UI or HA content is
# read or emitted.
timeout 15 curl -fsSI --max-time 10 "$ENGINEER_URL" >/dev/null \
  || fail fixed_engineer_url_unreachable 22

printf 'ENGINEER_FIXED_URL=PASS url=%s\n' "$ENGINEER_URL"
printf 'FINAL_NAVIGATION_PATH=Home Assistant sidebar > LifeOS Engineer\n'
printf 'FINAL_PANEL_URL=%s\n' "$ENGINEER_URL"
printf 'RUNTIME_CHECK=PASS job=%s\n' "$JOB_ID"
printf 'RESULT=PASS job=%s\n' "$JOB_ID"
