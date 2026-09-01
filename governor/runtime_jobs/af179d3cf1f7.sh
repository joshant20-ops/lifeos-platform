#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO=/home/joshan/lifeos-platform
readonly SOURCE="$REPO/homelab/live/usr/local/sbin/lifeos-root-broker"
readonly DESTINATION=/usr/local/sbin/lifeos-root-broker
readonly BACKUP_DIR=/var/lib/lifeos-control/root-broker-backups
readonly SOCKET=/run/lifeos-root-broker.sock

fail() { printf 'RESULT=FAIL\nREASON=%s\n' "$1" >&2; exit 1; }
run() { timeout "$1" "${@:2}"; }

[[ $(id -u) -eq 0 ]] || fail root_activation_required
[[ $(hostname) == Docker ]] || fail wrong_host
[[ -d "$REPO/.git" ]] || fail canonical_repository_missing
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail unsafe_canonical_broker
[[ -f "$DESTINATION" && ! -L "$DESTINATION" ]] || fail unsafe_live_broker
HEAD=$(git -C "$REPO" rev-parse HEAD); readonly HEAD
MAIN=$(git -C "$REPO" rev-parse main); readonly MAIN
ORIGIN=$(git -C "$REPO" rev-parse refs/remotes/origin/main); readonly ORIGIN
[[ "$HEAD" == "$MAIN" && "$HEAD" == "$ORIGIN" ]] || fail canonical_publication_mismatch
[[ -z $(git -C "$REPO" status --porcelain --untracked-files=no) ]] || fail canonical_repository_dirty
git -C "$REPO" ls-files --error-unmatch -- homelab/live/usr/local/sbin/lifeos-root-broker >/dev/null || fail broker_untracked
WORKTREE_SHA=$(sha256sum "$SOURCE" | awk '{print $1}'); readonly WORKTREE_SHA
HEAD_SHA=$(git -C "$REPO" show "$HEAD:homelab/live/usr/local/sbin/lifeos-root-broker" | sha256sum | awk '{print $1}'); readonly HEAD_SHA
ORIGIN_SHA=$(git -C "$REPO" show "refs/remotes/origin/main:homelab/live/usr/local/sbin/lifeos-root-broker" | sha256sum | awk '{print $1}'); readonly ORIGIN_SHA
[[ "$WORKTREE_SHA" == "$HEAD_SHA" && "$WORKTREE_SHA" == "$ORIGIN_SHA" ]] || fail broker_blob_mismatch
python3 -m py_compile "$SOURCE" || fail broker_compile_failed

install -d -m 0750 "$BACKUP_DIR"
install -d -o joshan -g joshan -m 0750 /var/lib/lifeos-backlog-runner
install -d -m 0755 /etc/lifeos
if [[ ! -s /etc/lifeos/backlog-dispatcher.token ]]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' >/etc/lifeos/backlog-dispatcher.token
fi
chown root:root /etc/lifeos/backlog-dispatcher.token
chmod 0600 /etc/lifeos/backlog-dispatcher.token
readonly BACKUP="$BACKUP_DIR/af179d3cf1f7-${WORKTREE_SHA}.bak"
install -m 0755 "$DESTINATION" "$BACKUP"
rollback() {
  install -m 0755 "$BACKUP" "$DESTINATION"
  run 30s systemctl restart lifeos-root-broker.socket || true
}
trap 'rollback' ERR
TEMP=$(mktemp /usr/local/sbin/.lifeos-root-broker.af179d3cf1f7.XXXXXX); readonly TEMP
install -m 0755 "$SOURCE" "$TEMP"
[[ $(sha256sum "$TEMP" | awk '{print $1}') == "$WORKTREE_SHA" ]] || fail temporary_hash_mismatch
mv -f "$TEMP" "$DESTINATION"
install -d -m 0755 /etc/systemd/system/lifeos-autonomous-agent.service.d
run 30s systemctl restart lifeos-root-broker.socket
run 15s systemctl is-active --quiet lifeos-root-broker.socket || fail broker_socket_inactive

DEPLOY_RESULTS=$(python3 - "$SOCKET" <<'PY'
import json, socket, sys
for operation, job in (("deploy-autonomous-agent", "af179d3cf1f7-agent"),
                       ("deploy-backlog-runner", "af179d3cf1f7-backlog")):
    request = {"operation": operation, "job_id": job, "target": "pi5"}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(180); client.connect(sys.argv[1])
        client.sendall((json.dumps(request) + "\n").encode()); client.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk: break
            chunks.append(chunk)
    response = json.loads(b"".join(chunks))
    assert response.get("status") == "PASS", response
    print(operation + "=PASS")
PY
)
grep -qx 'deploy-autonomous-agent=PASS' <<<"$DEPLOY_RESULTS" || fail autonomous_deployment_failed
grep -qx 'deploy-backlog-runner=PASS' <<<"$DEPLOY_RESULTS" || fail backlog_deployment_failed
if systemctl is-active --quiet lifeos-backlog-runner.timer; then fail backlog_timer_must_remain_stopped; fi
trap - ERR
printf '%s\n' "$DEPLOY_RESULTS"
printf 'BROKER_BOOTSTRAP=PASS\nBROKER_SHA256=%s\nBACKLOG_TIMER=INACTIVE\nRESULT=PASS\n' "$WORKTREE_SHA"
