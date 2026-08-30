#!/bin/sh
# Invocation template: the scheduler supplies values selected from providers.json.
set -eu

: "${LIFEOS_SELECTED_BASE_URL:?governor-selected base URL required}"
: "${LIFEOS_SELECTED_MODEL:?governor-selected model required}"
: "${LIFEOS_CONTEXT_PACKET:?compact context packet required}"
: "${LIFEOS_SELECTED_API_KEY:?runtime provider credential required}"

export LLM_BASE_URL="$LIFEOS_SELECTED_BASE_URL"
export LLM_MODEL="$LIFEOS_SELECTED_MODEL"
export LLM_API_KEY="$LIFEOS_SELECTED_API_KEY"
export OPENHANDS_SUPPRESS_BANNER=1

# OpenHands CLI 1.16+ reads LLM settings from environment only when
# --override-with-envs is supplied. Headless mode is bounded by the queue
# worker timeout and runs only inside the isolated job worktree.
exec openhands \
  --override-with-envs \
  --headless \
  --json \
  --exit-without-confirmation \
  --task "Read the LifeOS job and instructions from the compact context packet at $LIFEOS_CONTEXT_PACKET. Work only in the current git worktree. Implement the requested issue, run relevant deterministic tests, and leave reviewable workspace changes. Do not merge, push, deploy, access production, or expose secrets."
