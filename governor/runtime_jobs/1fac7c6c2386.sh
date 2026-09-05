#!/usr/bin/env bash
set -Eeuo pipefail
# Historical issue #14 privacy-path probe retained as evidence.
# Current production verification is performed by the governed autonomous-agent
# acceptance path; do not mutate runtime from this archived launcher.
echo 'ISSUE_14_PROBE=ARCHIVED_READ_ONLY'
echo 'NEXT_RUNTIME_CHECK=none'
