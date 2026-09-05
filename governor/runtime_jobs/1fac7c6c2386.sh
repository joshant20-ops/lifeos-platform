#!/usr/bin/env bash
set -Eeuo pipefail

readonly AGENT_URL=${LIFEOS_AGENT_URL:-http://127.0.0.1:8790}
readonly PLATFORM=${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}
readonly LIVE_AGENT=${LIFEOS_LIVE_AGENT:-/usr/local/libexec/lifeos-autonomous-agent}
readonly REQUEST='Issue 14 fresh privacy-classifier probe v2: Perform a read-only Engineer audit of repository code and documentation for consistency using only cloud-safe repository content. Report concrete findings and focused test evidence.'

echo 'ISSUE_14_PROBE=RETAINED'
echo 'NOTE=Use current governed autonomous-agent evidence before executing this historical launcher.'
echo 'NEXT_RUNTIME_CHECK=none'
