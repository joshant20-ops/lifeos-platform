#!/usr/bin/env bash
set -euo pipefail

JOB_COMMIT=e39e5f31d217f0154c41d8080e944a72b3d730e9
REPO=/home/joshan/lifeos-platform
DESIRED="$REPO/homelab/live/usr/local/sbin/lifeos-root-broker"
LIVE=/usr/local/sbin/lifeos-root-broker

fail() {
  echo "FAIL=$1"
  exit 1
}

timeout 10s test -f "$DESIRED" || fail desired_broker_missing
timeout 10s test -f "$LIVE" || fail live_broker_missing
timeout 10s git -C "$REPO" cat-file -e "${JOB_COMMIT}^{commit}" || fail protected_commit_missing

desired_sha=$(timeout 10s sha256sum "$DESIRED" | awk '{print $1}')
live_sha=$(timeout 10s sha256sum "$LIVE" | awk '{print $1}')
echo "PROTECTED_COMMIT=$JOB_COMMIT"
echo "DESIRED_BROKER_SHA256=$desired_sha"
echo "LIVE_BROKER_SHA256=$live_sha"

if cmp -s "$DESIRED" "$LIVE"; then
  echo "ACTIVATION_STATE=already-installed"
else
  echo "ACTIVATION_STATE=HUMAN_ACTION_REQUIRED"
fi

for unit in lifeos-root-broker.socket lifeos-root-broker.service lifeos-autonomous-agent.service lifeos-engineer.service; do
  state=$(timeout 10s systemctl is-active "$unit" 2>/dev/null || true)
  echo "UNIT_${unit//[^A-Za-z0-9]/_}=${state:-not-found-or-inactive}"
done

# A malformed request is safe against both the old and proposed broker and
# demonstrates that the live socket remains fail-closed without activating it.
python3 - <<'PY'
import json
import socket

request = {"operation": "deploy-engineer-runtime", "job_id": "assurance-probe", "target": "pi5", "command": "id"}
try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect('/run/lifeos-root-broker.sock')
        client.sendall((json.dumps(request) + '\n').encode())
        client.shutdown(socket.SHUT_WR)
        response = client.recv(8192).decode(errors='replace')
except Exception as exc:
    print('MALFORMED_REQUEST=FAIL:' + type(exc).__name__)
    raise SystemExit(1)
if 'REJECTED' not in response:
    print('MALFORMED_REQUEST=FAIL:broker_did_not_reject')
    raise SystemExit(1)
print('MALFORMED_REQUEST=PASS')
PY

if command -v gh >/dev/null 2>&1; then
  ci=$(timeout 20s gh api "repos/joshant20-ops/lifeos-platform/commits/$JOB_COMMIT/check-runs" \
    --jq '[.check_runs[] | {name, status, conclusion}]' 2>/dev/null || true)
  if [[ -n "$ci" ]]; then
    echo "GITHUB_CHECK_RUNS=$ci"
  else
    echo "GITHUB_CHECK_RUNS=unavailable"
  fi
else
  echo "GITHUB_CHECK_RUNS=gh-not-installed"
fi

echo "POLICY=explicit protected-control approval required"
echo "BOUNDED_ACTIVATION=publish one checksummed root-broker scoped control job that backs up and installs only $LIVE from $DESIRED, restarts only the discovered lifeos-root-broker socket/service unit, verifies broker and Engineer services, and rolls back the broker on failure"
echo "PASS=assurance_runtime_evidence_collected_without_activation"
