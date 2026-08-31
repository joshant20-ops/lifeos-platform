#!/usr/bin/env bash
set -euo pipefail

REPO="/home/joshan/workspace/lifeos-platform"
RUNNER_SRC="$REPO/engineer/runner/lifeos-engineer-runner.py"
RUNNER_DST="/home/joshan/.local/bin/lifeos-engineer-runner"
SERVICE="/etc/systemd/system/lifeos-engineer-runner.service"
TIMER="/etc/systemd/system/lifeos-engineer-runner.timer"

echo "===== LIFEOS ENGINEER RUNNER BOOTSTRAP ====="
echo "Expected: <60 sec"

[[ "$(hostname)" == "Engineer" ]] || { echo "FAIL: must run on Engineer"; exit 20; }
[[ -d "$REPO/.git" ]] || { echo "FAIL: repo missing at $REPO"; exit 21; }

cd "$REPO"
git fetch origin main
git merge --ff-only origin/main

[[ -f "$RUNNER_SRC" ]] || { echo "FAIL: canonical runner missing"; exit 22; }
python3 -m py_compile "$RUNNER_SRC"

mkdir -p /home/joshan/.local/bin /home/joshan/.local/state/lifeos-engineer-runner
install -m 0755 "$RUNNER_SRC" "$RUNNER_DST"

sudo tee "$SERVICE" >/dev/null <<'UNIT'
[Unit]
Description=LifeOS Engineer GitHub job runner
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=joshan
Group=joshan
WorkingDirectory=/home/joshan/workspace/lifeos-platform
Environment=LIFEOS_PLATFORM_REPO=/home/joshan/workspace/lifeos-platform
ExecStart=/home/joshan/.local/bin/lifeos-engineer-runner
Nice=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
ReadWritePaths=/home/joshan/workspace/lifeos-platform /home/joshan/.local/state/lifeos-engineer-runner

[Install]
WantedBy=multi-user.target
UNIT

sudo tee "$TIMER" >/dev/null <<'UNIT'
[Unit]
Description=Run LifeOS Engineer job runner every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Persistent=true
Unit=lifeos-engineer-runner.service

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now lifeos-engineer-runner.timer
sudo systemctl start lifeos-engineer-runner.service

echo
echo "===== VERIFY ====="
systemctl is-enabled lifeos-engineer-runner.timer
systemctl is-active lifeos-engineer-runner.timer
systemctl status lifeos-engineer-runner.timer --no-pager -n 8 || true
journalctl -u lifeos-engineer-runner.service -n 20 --no-pager -o cat || true

echo
echo "RESULT=PASS"
echo "TARGET=engineer"
echo "INTERVAL=5m"
echo "RUNNER=$RUNNER_DST"
