#!/usr/bin/env bash
set -euo pipefail

readonly ENGINEER_HOST="engineer"
readonly ENGINEER_REPO="/home/joshan/workspace/lifeos-platform"
readonly SSH_TIMEOUT="20"
readonly SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes)

fail() {
  echo "RUNTIME_CHECK=FAIL"
  echo "BARRIER=$1"
  exit 1
}

command -v timeout >/dev/null || fail timeout_unavailable_on_pi5
command -v ssh >/dev/null || fail ssh_unavailable_on_pi5

timeout "${SSH_TIMEOUT}s" ssh "${SSH_ARGS[@]}" "$ENGINEER_HOST" \
  "test -d '$ENGINEER_REPO/.git' && command -v python3 >/dev/null && command -v openhands >/dev/null" \
  || fail engineer_workspace_python_or_openhands_unavailable

timeout "${SSH_TIMEOUT}s" ssh "${SSH_ARGS[@]}" "$ENGINEER_HOST" \
  "test ! -e /home/joshan/.openhands/provider-secrets.env || test \"\$(stat -c %a /home/joshan/.openhands/provider-secrets.env)\" = 600" \
  || fail provider_secrets_permissions_not_0600

audit_json="$(timeout "${SSH_TIMEOUT}s" ssh "${SSH_ARGS[@]}" "$ENGINEER_HOST" \
  "cd '$ENGINEER_REPO' && ENGINEER_HOME=/home/joshan python3 engineer/cleanup_audit.py")" \
  || fail cleanup_audit_failed

python3 -c 'import json,sys; x=json.loads(sys.stdin.read()); assert x["mode"] == "dry-run"; assert x["automatic_deletion"] == "DISABLED"; assert x["safe_to_remove"] == []' \
  <<<"$audit_json" || fail cleanup_safety_contract_failed

echo "RUNTIME_CHECK=PASS"
echo "OPENHANDS_COMMAND=AVAILABLE"
echo "SECRETS_PERMISSION=0600_OR_ABSENT"
echo "CLEANUP_MODE=DRY_RUN"
echo "AUTOMATIC_DELETION=DISABLED"
echo "SAFE_TO_REMOVE_COUNT=0"
