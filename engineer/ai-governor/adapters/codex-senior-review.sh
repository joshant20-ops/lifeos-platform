#!/bin/sh
# Senior-review invocation template. The human/scheduler must enforce eligibility
# and the normal one-consolidated-review-per-day policy before invoking it.
set -eu

: "${LIFEOS_REVIEW_PROMPT:?path to consolidated, secret-free review prompt required}"
: "${LIFEOS_REVIEW_WORKSPACE:?target workspace required}"

# Codex authentication is managed separately through ChatGPT; no secret is mapped.
# Confirm the exact non-interactive flags against the installed CLI before use.
exec codex exec --cwd "$LIFEOS_REVIEW_WORKSPACE" "$(sed -n '1,240p' "$LIFEOS_REVIEW_PROMPT")"
