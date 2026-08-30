#!/bin/sh
# Invocation template: the scheduler supplies values selected from providers.json.
set -eu

: "${LIFEOS_SELECTED_BASE_URL:?governor-selected base URL required}"
: "${LIFEOS_SELECTED_MODEL:?governor-selected model required}"
: "${LIFEOS_CONTEXT_PACKET:?compact context packet required}"

# Map the selected provider's external secret at runtime. Never write it here.
: "${LIFEOS_SELECTED_API_KEY:?runtime provider credential required}"

export LLM_BASE_URL="$LIFEOS_SELECTED_BASE_URL"
export LLM_MODEL="$LIFEOS_SELECTED_MODEL"
export LLM_API_KEY="$LIFEOS_SELECTED_API_KEY"

# Adjust flags for the installed OpenHands CLI version. Keep workspace and task
# targeted; this template intentionally does not grant production access.
exec openhands --llm-model "$LLM_MODEL" --llm-base-url "$LLM_BASE_URL" \
  --task "Use the compact context packet at $LIFEOS_CONTEXT_PACKET"
