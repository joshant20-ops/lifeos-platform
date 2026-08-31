#!/usr/bin/env bash
set -euo pipefail

if [[ "$(hostname)" != "Engineer" && "$(hostname)" != "AI" && "$(hostname)" != "ai-vm" ]]; then
  echo "Refusing unexpected host: $(hostname)"
  exit 20
fi

CONTROL=/home/joshan/lifeos-pi-control
PLATFORM=/home/joshan/workspace/lifeos-platform

command -v git >/dev/null
command -v python3 >/dev/null

if [[ ! -d "$CONTROL/.git" ]]; then
  git clone git@github.com:joshant20-ops/lifeos-pi-control.git "$CONTROL"
fi

git -C "$CONTROL" fetch origin main
git -C "$CONTROL" reset --hard origin/main

sudo install -d -m 0755 /etc/lifeos-control
printf '%s\n' '{"target_id":"ai-vm","aliases":["Engineer","z97"]}' | sudo tee /etc/lifeos-control/identity.json >/dev/null
sudo chown root:root /etc/lifeos-control/identity.json
sudo chmod 0644 /etc/lifeos-control/identity.json

install -Dm0755 "$PLATFORM/ai-vm/runner/lifeos-ai-vm-runner.py" "$HOME/.local/bin/lifeos-ai-vm-runner"

mkdir -p "$HOME/.config/systemd/user"
cat >"$HOME/.config/systemd/user/lifeos-ai-vm-runner.service" <<'UNIT'
[Unit]
Description=LifeOS AI VM diagnostic GitHub runner
After=network-online.target

[Service]
Type=oneshot
Environment=HOME=/home/joshan
Environment=LIFEOS_CONTROL_REPO=/home/joshan/lifeos-pi-control
ExecStart=/home/joshan/.local/bin/lifeos-ai-vm-runner
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/home/joshan/lifeos-pi-control /home/joshan/.local/state/lifeos-ai-vm
UNIT

cat >"$HOME/.config/systemd/user/lifeos-ai-vm-runner.timer" <<'UNIT'
[Unit]
Description=Poll LifeOS AI VM diagnostic queue

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now lifeos-ai-vm-runner.timer
systemctl --user start lifeos-ai-vm-runner.service

echo "AI_VM_RUNNER=installed"
echo "MODE=diagnostic-only"
