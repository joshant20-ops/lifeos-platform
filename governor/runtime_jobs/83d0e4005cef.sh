#!/usr/bin/env bash
set -Eeuo pipefail

readonly JOB_ID=83d0e4005cef
readonly REPO=/home/joshan/lifeos-platform
readonly IDENTITY=/etc/lifeos-control/identity.json
readonly BROKER_SOURCE="$REPO/homelab/live/usr/local/sbin/lifeos-root-broker"
readonly BROKER_DESTINATION=/usr/local/sbin/lifeos-root-broker
readonly LAUNCHER_RELATIVE=governor/runtime_jobs/83d0e4005cef.sh
readonly FAILED_BOOTSTRAP_RELATIVE=governor/runtime_jobs/af179d3cf1f7.sh
readonly FAILED_BOOTSTRAP_SHA256=37707030baed18a8717a79ec6fcc116f8be893e6a1ae6b3fac76b50f971efb0d
readonly BACKUP_DIR=/var/lib/lifeos-control/root-broker-backups
readonly SOCKET=/run/lifeos-root-broker.sock

fail() { printf 'RESULT=FAIL\nREASON=%s\n' "$1" >&2; exit 1; }
run() { local limit=$1; shift; timeout "$limit" "$@"; }
sha() { sha256sum "$1" | awk '{print $1}'; }

[[ $(id -u) -eq 0 ]] || fail root_activation_required
[[ -d "$REPO/.git" ]] || fail canonical_repository_missing
[[ -f "$IDENTITY" && ! -L "$IDENTITY" ]] || fail identity_contract_missing_or_unsafe
TARGET_ID=$(python3 - "$IDENTITY" <<'PY'
import json, pathlib, sys
try:
    value = json.loads(pathlib.Path(sys.argv[1]).read_text())
    target = value.get("target_id") if isinstance(value, dict) else None
except Exception:
    raise SystemExit(1)
if not isinstance(target, str) or not target:
    raise SystemExit(1)
print(target)
PY
) || fail identity_contract_invalid
readonly TARGET_ID

HEAD=$(git -C "$REPO" rev-parse HEAD) || fail head_unavailable
MAIN=$(git -C "$REPO" rev-parse main) || fail main_unavailable
ORIGIN=$(git -C "$REPO" rev-parse refs/remotes/origin/main) || fail origin_main_unavailable
readonly HEAD MAIN ORIGIN
[[ "$HEAD" == "$MAIN" && "$HEAD" == "$ORIGIN" ]] || fail canonical_publication_mismatch
[[ -z $(git -C "$REPO" status --porcelain --untracked-files=no) ]] || fail canonical_repository_dirty

verify_published_file() {
  local relative=$1 path="$REPO/$1" worktree_sha head_sha origin_sha
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe_canonical_file:$relative"
  git -C "$REPO" ls-files --error-unmatch -- "$relative" >/dev/null || fail "untracked_file:$relative"
  worktree_sha=$(sha "$path")
  head_sha=$(git -C "$REPO" show "$HEAD:$relative" | sha256sum | awk '{print $1}') || fail "head_blob_unavailable:$relative"
  origin_sha=$(git -C "$REPO" show "refs/remotes/origin/main:$relative" | sha256sum | awk '{print $1}') || fail "origin_blob_unavailable:$relative"
  [[ "$worktree_sha" == "$head_sha" && "$worktree_sha" == "$origin_sha" ]] || fail "published_blob_mismatch:$relative"
  printf '%s\n' "$worktree_sha"
}

[[ -x "$REPO/$LAUNCHER_RELATIVE" ]] || fail launcher_not_executable
LAUNCHER_SHA=$(verify_published_file "$LAUNCHER_RELATIVE"); readonly LAUNCHER_SHA
BROKER_SHA=$(verify_published_file homelab/live/usr/local/sbin/lifeos-root-broker); readonly BROKER_SHA
[[ $(sha "$REPO/$FAILED_BOOTSTRAP_RELATIVE") == "$FAILED_BOOTSTRAP_SHA256" ]] || fail historical_bootstrap_mutated
verify_published_file "$FAILED_BOOTSTRAP_RELATIVE" >/dev/null
python3 -m py_compile "$BROKER_SOURCE" || fail broker_compile_failed
[[ -f "$BROKER_DESTINATION" && ! -L "$BROKER_DESTINATION" ]] || fail unsafe_live_broker

install -d -m 0750 "$BACKUP_DIR"
readonly BACKUP="$BACKUP_DIR/$JOB_ID-$BROKER_SHA.bak"
install -m 0755 "$BROKER_DESTINATION" "$BACKUP"
ROLLBACK_REQUIRED=0
rollback() {
  [[ "$ROLLBACK_REQUIRED" -eq 1 ]] || return 0
  install -m 0755 "$BACKUP" "$BROKER_DESTINATION"
  run 30s systemctl restart lifeos-root-broker.socket || true
}
trap rollback EXIT
TEMP=$(mktemp /usr/local/sbin/.lifeos-root-broker."$JOB_ID".XXXXXX); readonly TEMP
install -m 0755 "$BROKER_SOURCE" "$TEMP"
[[ $(sha "$TEMP") == "$BROKER_SHA" ]] || fail temporary_broker_hash_mismatch
mv -f "$TEMP" "$BROKER_DESTINATION"
ROLLBACK_REQUIRED=1
run 30s systemctl restart lifeos-root-broker.socket
run 15s systemctl is-active --quiet lifeos-root-broker.socket || fail broker_socket_inactive

DEPLOY_RESULTS=$(python3 - "$SOCKET" "$TARGET_ID" "$JOB_ID" "$HEAD" <<'PY'
import json, socket, sys
sock, target, job, commit = sys.argv[1:]
for operation, suffix in (("deploy-autonomous-agent", "agent"), ("deploy-backlog-runner", "backlog")):
    request = {"operation": operation, "job_id": f"{job}-{suffix}", "target": target}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(180)
        client.connect(sock)
        client.sendall((json.dumps(request, sort_keys=True) + "\n").encode())
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk: break
            chunks.append(chunk)
    response = json.loads(b"".join(chunks))
    if response.get("status") != "PASS" or response.get("target") != target or response.get("source_commit") != commit:
        raise SystemExit(f"{operation} deployment mismatch")
    print(operation + "=PASS")
PY
) || fail bounded_deployment_failed
grep -qx 'deploy-autonomous-agent=PASS' <<<"$DEPLOY_RESULTS" || fail autonomous_deployment_failed
grep -qx 'deploy-backlog-runner=PASS' <<<"$DEPLOY_RESULTS" || fail backlog_deployment_failed

run 15s systemctl stop lifeos-backlog-runner.timer
if systemctl is-active --quiet lifeos-backlog-runner.timer; then fail backlog_timer_not_stopped; fi
run 15s curl --fail --silent --show-error http://127.0.0.1:8790/health >/dev/null || fail governor_health_failed

for mapping in \
  'governor/autonomous_agent.py:/usr/local/libexec/lifeos-autonomous-agent' \
  'governor/target_identity.py:/usr/local/libexec/target_identity.py' \
  'governor/backlog_runner.py:/usr/local/libexec/lifeos-backlog-runner' \
  'governor/systemd/lifeos-backlog-runner.service:/etc/systemd/system/lifeos-backlog-runner.service' \
  'governor/systemd/lifeos-backlog-runner.timer:/etc/systemd/system/lifeos-backlog-runner.timer' \
  'governor/systemd/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf:/etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf'; do
  relative=${mapping%%:*}; live=${mapping#*:}
  [[ -f "$live" && ! -L "$live" ]] || fail "live_file_missing_or_unsafe:$live"
  [[ $(sha "$REPO/$relative") == $(sha "$live") ]] || fail "live_source_mismatch:$relative"
done

ROLLBACK_REQUIRED=0
trap - EXIT
printf '%s\n' "$DEPLOY_RESULTS"
printf 'TARGET_ID_SOURCE=%s\nAUTHORITATIVE_TARGET_ID=%s\n' "$IDENTITY" "$TARGET_ID"
printf 'CANONICAL_COMMIT=%s\nORIGIN_MAIN=%s\n' "$HEAD" "$ORIGIN"
printf 'NEW_BOOTSTRAP_PATH=%s\nNEW_BOOTSTRAP_SHA256=%s\nNEW_BOOTSTRAP_COMMIT=%s\n' "$LAUNCHER_RELATIVE" "$LAUNCHER_SHA" "$HEAD"
printf 'NEW_BOOTSTRAP_PUBLISHED=YES\nBROKER_SHA256=%s\n' "$BROKER_SHA"
printf 'GOVERNOR_HEALTH=PASS\nLIVE_GOVERNOR_CANONICAL=PASS\nBACKLOG_RUNNER_DEPLOYMENT=PASS\nBACKLOG_TIMER=STOPPED\nRESULT=PASS\n'
