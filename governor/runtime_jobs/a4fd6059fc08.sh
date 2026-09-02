#!/usr/bin/env bash
set -Eeuo pipefail

# Job-specific Watchman entrypoint for issue #25.  The event has ended, so the
# reviewed post-event assurance launcher is reused without replaying event
# writes.  Pinning its digest prevents this wrapper from silently broadening
# the privileged operation.
readonly REPO=/home/joshan/lifeos-platform
readonly DELEGATE="$REPO/governor/runtime_jobs/a181c9270e39.sh"
readonly DELEGATE_SHA=bb2f33348b14ff6744e47e8ab7acc779c6793f73c0454c21ad2cd6de9777b175

fail() {
  local barrier=$1
  printf 'FAIL=%s\n' "$barrier"
  printf '%s\n' \
    'ISSUE_VALIDITY=VALID' \
    'LIFEOS_WORK_STATE=BLOCKED' \
    "BARRIER=$barrier" \
    'NEXT_AUTONOMOUS_ACTION=publish the canonical reviewed delegate, then rerun this launcher through Watchman' \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    'RESULT=BLOCKED' \
    'TESTS=job-specific entrypoint validation failed' \
    'NEXT_RUNTIME_CHECK=rerun governor/runtime_jobs/a4fd6059fc08.sh through Watchman after correcting the named barrier'
  exit 1
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
[[ -f "$DELEGATE" && ! -L "$DELEGATE" ]] || fail reviewed_delegate_missing_or_symlink
[[ "$(sha256sum "$DELEGATE" | awk '{print $1}')" == "$DELEGATE_SHA" ]] || fail reviewed_delegate_hash_mismatch

exec timeout --signal=TERM --kill-after=10s 300s "$DELEGATE"
