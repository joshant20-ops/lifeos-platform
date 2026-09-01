#!/usr/bin/env bash
set -euo pipefail
readonly JOB_ID=9eb04949f627
readonly REPO=/home/joshan/lifeos-platform
readonly ENGINEER_HOST=192.168.0.203
readonly SSH_TARGET=joshan@${ENGINEER_HOST}
readonly SSH_ARGS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes)
fail(){ printf 'RESULT=FAIL reason=%s\n' "$1"; exit "${2:-1}"; }
[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker 20
[[ -f "$REPO/engineer/cleanup_audit.py" ]] || fail source_not_published
python3 -m py_compile "$REPO/engineer/provider_router.py" "$REPO/engineer/openhands_worker.py" "$REPO/engineer/cleanup_audit.py"
timeout 20 ssh "${SSH_ARGS[@]}" "$SSH_TARGET" 'test "$(stat -c %a /home/joshan/.openhands/provider-secrets.env 2>/dev/null || echo absent)" = 600 || test ! -e /home/joshan/.openhands/provider-secrets.env' \
  || fail secrets_mode_not_0600
# Copy only repository-owned audit code to stdin. It reads names/metadata only and emits no file contents.
timeout 30 ssh "${SSH_ARGS[@]}" "$SSH_TARGET" 'ENGINEER_HOME=/home/joshan python3 -' < "$REPO/engineer/cleanup_audit.py" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["automatic_deletion"]=="DISABLED" and d["safe_to_remove"]==[]; print("CLEANUP_DRY_RUN=PASS items=%d"%len(d["items"]))' \
  || fail cleanup_audit_failed
timeout 20 ssh "${SSH_ARGS[@]}" "$SSH_TARGET" 'command -v openhands >/dev/null && test -d /home/joshan/workspace/lifeos-platform/.git' \
  || fail openhands_or_workspace_missing
printf 'OPENHANDS_PREFLIGHT=PASS\nAUTOMATIC_DELETION=DISABLED\nDIRECT_PRODUCTION_MUTATION=NONE\nRESULT=PASS\n'
