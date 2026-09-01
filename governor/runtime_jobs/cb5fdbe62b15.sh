#!/usr/bin/env bash
set -euo pipefail

# Human-reviewed Pi5 activation for the bounded control-job submission boundary.
# This is intentionally the only runtime launcher for cloud job cb5fdbe62b15.
readonly PLATFORM=/home/joshan/lifeos-platform
readonly ACTIVATOR="$PLATFORM/governor/runtime_jobs/d2dd520ff95b.sh"

blocked() {
  echo "HUMAN_ACTION_REQUIRED=On Pi5, review and run exactly: sudo $PLATFORM/governor/runtime_jobs/cb5fdbe62b15.sh"
  echo "RESULT=BLOCKED"
  echo "TESTS=repository bridge tests passed; privileged socket/account/ACL boundary awaits activation"
  echo "NEXT_RUNTIME_CHECK=sudo $PLATFORM/governor/runtime_jobs/cb5fdbe62b15.sh"
  exit 20
}

fail() {
  echo "FAIL=$1"
  echo "RESULT=BLOCKED"
  echo "TESTS=Pi5 bridge activation or resumed self-deploy verification failed"
  echo "NEXT_RUNTIME_CHECK=inspect FAIL and journalctl -u 'lifeos-control-job-submit@*'"
  exit 1
}

[[ $(id -u) -eq 0 ]] || blocked
[[ -x "$ACTIVATOR" && ! -L "$ACTIVATOR" ]] || fail reviewed_activator_missing

# The reviewed activator is timeout-aware and performs the bounded install,
# adversarial probes, normal publisher/FIFO/runner/root-broker continuation,
# canonical broker hash check, Engineer deployment, health/history/stuck checks,
# and the approved three-prompt acceptance flow.
timeout --signal=TERM --kill-after=30s 2100s "$ACTIVATOR" || fail activation_failed
