#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
SOURCE="$PLATFORM/homelab/live/usr/local/sbin/lifeos-deploy-gateway"
DEST=/usr/local/sbin/lifeos-deploy-gateway
SUDOERS=/etc/sudoers.d/lifeos-github-deploy-gateway

fail(){ echo "ERROR: $*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo'
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail 'canonical gateway source missing or symlinked'

# Repository ownership must remain with joshan even when this installer is root.
HEAD=$(runuser -u joshan -- env -i HOME=/home/joshan PATH=/usr/bin:/bin LANG=C.UTF-8 \
  git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runuser -u joshan -- env -i HOME=/home/joshan PATH=/usr/bin:/bin LANG=C.UTF-8 \
  git -C "$PLATFORM" rev-parse origin/main)
STATUS=$(runuser -u joshan -- env -i HOME=/home/joshan PATH=/usr/bin:/bin LANG=C.UTF-8 \
  git -C "$PLATFORM" status --porcelain)
[[ "$HEAD" == "$ORIGIN" ]] || fail 'platform HEAD must equal origin/main'
[[ -z "$STATUS" ]] || fail 'platform worktree must be clean'

python3 -m py_compile "$SOURCE"
install -o root -g root -m 0755 "$SOURCE" "$DEST"

cat >"$SUDOERS" <<'EOF'
# LifeOS GitHub runner privilege boundary.
# The executable itself contains the fixed operation allow-list and rejects
# arbitrary commands/paths/arguments.
Cmnd_Alias LIFEOS_DEPLOY_GATEWAY = /usr/local/sbin/lifeos-deploy-gateway *
joshan ALL=(root) NOPASSWD: LIFEOS_DEPLOY_GATEWAY
EOF
chmod 0440 "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

# Verify sudo permits only the gateway path we intentionally installed.
sudo -u joshan sudo -n "$DEST" __not_allowlisted__ >/tmp/lifeos-gateway-negative.out 2>&1 || rc=$?
rc=${rc:-0}
[[ "$rc" -eq 64 ]] || { cat /tmp/lifeos-gateway-negative.out >&2; fail "negative allow-list test returned rc=$rc"; }
rm -f /tmp/lifeos-gateway-negative.out

printf '%s\n' \
  'RESULT=PASS' \
  'LIFEOS_DEPLOY_GATEWAY_INSTALLED=YES' \
  'RUNNER_SUDO_SCOPE=ALLOWLISTED_GATEWAY_ONLY' \
  "PLATFORM_HEAD=$HEAD" \
  'NEXT_ACTION=register_dedicated_github_actions_runner_then_dispatch_check_workflow'
