#!/usr/bin/env bash
set -Eeuo pipefail

REPO=/home/joshan/lifeos-platform
JOB_ID=cdf57932bb2d
AGENT_SOURCE=$REPO/governor/autonomous_agent.py
AGENT_TARGET=/usr/local/libexec/lifeos-autonomous-agent
INSTALLER=$REPO/governor/scripts/install-backlog-runner-pi5.sh

fail() { printf 'RESULT=FAIL\nREASON=%s\n' "$1"; exit 1; }
[[ $(id -u) -eq 0 ]] || fail must_run_as_root
[[ $(hostname) == Docker ]] || fail must_run_on_pi5_Docker
[[ -f "$AGENT_SOURCE" && -x "$INSTALLER" ]] || fail canonical_sources_missing
command -v timeout >/dev/null || fail timeout_missing

python3 -m py_compile "$AGENT_SOURCE" || fail agent_compile_failed
install -o root -g root -m 0755 "$AGENT_SOURCE" "$AGENT_TARGET"
timeout 60s systemctl restart lifeos-autonomous-agent.service || fail governor_restart_failed
timeout 15s bash -c 'until curl -fsS --max-time 3 http://127.0.0.1:8790/health >/dev/null; do sleep 1; done' \
    || fail governor_health_failed
timeout 600s "$INSTALLER" || fail backlog_install_failed

systemctl is-active --quiet lifeos-autonomous-agent.service || fail governor_inactive
systemctl is-active --quiet lifeos-backlog-runner.timer || fail backlog_timer_inactive
grep -q 'LoadCredential=backlog-dispatcher.token' \
    /etc/systemd/system/lifeos-backlog-runner.service || fail runner_credential_missing
grep -q 'LoadCredential=backlog-dispatcher.token' \
    /etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf \
    || fail governor_credential_missing

printf 'RESULT=PASS\n'
printf 'JOB_ID=%s\n' "$JOB_ID"
printf 'DISPATCH_CAPABILITY=systemd credential installed for governor and backlog runner\n'
printf 'LIVE_DEPLOYMENT=governor restarted and backlog timer active\n'
printf 'ISSUE_6_REDISPATCH=normal backlog loop invoked; state and active-job guards prevent duplicates\n'
printf 'NEXT_RUNTIME_CHECK=inspect backlog runner state and Governor job stage for issue 6\n'
