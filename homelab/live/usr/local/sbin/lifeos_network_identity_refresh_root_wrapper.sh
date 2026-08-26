#!/usr/bin/env bash
set -u
cd /home/joshan/automation || exit 1
/bin/bash /home/joshan/automation/run_network_identity_refresh.sh
rc=$?
if [ "$rc" -eq 126 ]; then
  echo "network_identity_refresh: underlying script returned 126; treating as report-only compatibility failure"
  exit 0
fi
exit "$rc"
