#!/usr/bin/env bash
set -Eeuo pipefail
STATE=/var/lib/lifeos-backlog-runner/state.json
STATE_DIR=/var/lib/lifeos-backlog-runner
DROPIN=/etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo 'RESULT=FAIL'; echo 'REASON=root_required'; exit 1; }
echo 'CLEANUP_SCOPE=retired_backlog_runtime_only'
for p in "$STATE" "$DROPIN"; do
  if [[ -e "$p" ]]; then echo "BEFORE=PRESENT path=$p"; else echo "BEFORE=ABSENT path=$p"; fi
done
rm -f -- "$STATE" "$DROPIN"
if [[ -d "$STATE_DIR" ]] && [[ -z "$(find "$STATE_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then rmdir "$STATE_DIR"; fi
systemctl daemon-reload
systemctl restart lifeos-autonomous-agent.service
for _ in $(seq 1 20); do
  if curl -fsS --max-time 2 http://127.0.0.1:8790/health >/dev/null; then break; fi
  sleep 1
done
curl -fsS --max-time 3 http://127.0.0.1:8790/health >/dev/null
[[ ! -e "$STATE" ]]
[[ ! -e "$DROPIN" ]]
! systemctl show lifeos-autonomous-agent.service -p DropInPaths --value | grep -q 'backlog-dispatcher.conf'
echo 'RETIRED_BACKLOG_STATE=ABSENT'
echo 'RETIRED_BACKLOG_DROPIN=ABSENT'
echo 'GOVERNOR_HEALTH=PASS'
echo 'RESULT=PASS'
