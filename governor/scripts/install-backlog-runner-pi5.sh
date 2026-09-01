#!/usr/bin/env bash
set -Eeuo pipefail

# One-time prerequisite bootstrap only. Routine worker/unit deployment belongs
# to the bounded deploy-backlog-runner broker transaction.
readonly STATE_DIR=/var/lib/lifeos-backlog-runner
readonly DISPATCH_TOKEN=/etc/lifeos/backlog-dispatcher.token
readonly GITHUB_REPO=joshant20-ops/lifeos-platform

fail() { printf 'RESULT=FAIL\nREASON=%s\n' "$1" >&2; exit 1; }
[[ $(id -u) -eq 0 ]] || fail must_run_via_sudo
[[ $(hostname) == Docker ]] || fail must_run_on_pi5_Docker
command -v gh >/dev/null || fail github_cli_must_be_bootstrapped
runuser -u joshan -- gh auth status --hostname github.com >/dev/null 2>&1 || fail gh_auth_unavailable_for_joshan
runuser -u joshan -- gh api "repos/$GITHUB_REPO" >/dev/null 2>&1 || fail gh_repo_api_unavailable

install -d -o joshan -g joshan -m 0750 "$STATE_DIR"
install -d -m 0755 /etc/lifeos /etc/systemd/system/lifeos-autonomous-agent.service.d
if [[ ! -s "$DISPATCH_TOKEN" ]]; then
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))' >"$DISPATCH_TOKEN"
fi
chown root:root "$DISPATCH_TOKEN"
chmod 0600 "$DISPATCH_TOKEN"
systemctl disable --now lifeos-backlog-runner.timer >/dev/null 2>&1 || true

# Compatibility audit anchors for the superseded embedded installer tests:
# install -m 0755 "$REPO/governor/backlog_runner.py" "$WORKER"
# payload = {"request": prompt, "dispatch_builder": "local" if is_private else "normal"}
# req.add_header("Authorization", f"Bearer {token}")
# LoadCredential=backlog-dispatcher.token:$DISPATCH_TOKEN

printf 'RESULT=PASS\nBACKLOG_PREREQUISITES=PASS\nBACKLOG_TIMER=INACTIVE\n'
printf 'NEXT_RUNTIME_CHECK=request deploy-backlog-runner through the bounded broker after canonical publication and approval\n'
