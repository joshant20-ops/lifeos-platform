#!/usr/bin/env bash
set -Eeuo pipefail

REPO_FULL=joshant20-ops/lifeos-platform
REPO_URL=https://github.com/$REPO_FULL
PLATFORM=/home/joshan/lifeos-platform
RUNNER_DIR=/opt/actions-runner-lifeos
RUNNER_NAME=lifeos-pi5
RUNNER_LABEL=lifeos-pi5

fail(){ echo "ERROR: $*" >&2; exit 1; }
runj(){ runuser -u joshan -- env -i HOME=/home/joshan PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 "$@"; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo'
[[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] || fail 'runner bootstrap requires ARM64 host'

cd "$PLATFORM"
HEAD=$(runj git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runj git -C "$PLATFORM" rev-parse origin/main)
STATUS=$(runj git -C "$PLATFORM" status --porcelain)
[[ "$HEAD" == "$ORIGIN" ]] || fail 'platform HEAD must equal origin/main'
[[ -z "$STATUS" ]] || fail 'platform worktree must be clean'

# Install the narrow privilege gateway first.
bash "$PLATFORM/scripts/lifeos-install-github-runner-gateway.sh"

if systemctl list-unit-files --no-pager | grep -q 'actions.runner.*lifeos-pi5.*service'; then
  echo 'RUNNER_SERVICE_ALREADY_PRESENT=YES'
  systemctl --no-pager --full status "$(systemctl list-unit-files --no-legend | awk '/actions\.runner\..*lifeos-pi5.*\.service/{print $1; exit}')" | head -25 || true
  echo 'RESULT=PASS'
  echo 'GITHUB_RUNNER_BOOTSTRAPPED=ALREADY_PRESENT'
  exit 0
fi

[[ ! -e "$RUNNER_DIR/.runner" ]] || fail 'runner directory appears configured but no service was discovered'

TAG=$(runj gh api repos/actions/runner/releases/latest --jq .tag_name)
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "unexpected actions runner tag: $TAG"
VERSION=${TAG#v}
URL="https://github.com/actions/runner/releases/download/$TAG/actions-runner-linux-arm64-$VERSION.tar.gz"

mkdir -p "$RUNNER_DIR"
chown joshan:joshan "$RUNNER_DIR"
TMP=$(mktemp -d /tmp/lifeos-actions-runner.XXXXXX)
chown joshan:joshan "$TMP"
chmod 700 "$TMP"
trap 'rm -rf "$TMP"' EXIT
runj curl -fL --retry 3 --retry-delay 2 "$URL" -o "$TMP/runner.tgz"
tar -xzf "$TMP/runner.tgz" -C "$RUNNER_DIR"
chown -R joshan:joshan "$RUNNER_DIR"

# Token is short-lived and intentionally never printed or persisted by us.
TOKEN=$(runj gh api -X POST "repos/$REPO_FULL/actions/runners/registration-token" --jq .token)
[[ -n "$TOKEN" ]] || fail 'failed to obtain GitHub runner registration token'

runj bash -lc "cd '$RUNNER_DIR' && ./config.sh --unattended --replace --url '$REPO_URL' --token '$TOKEN' --name '$RUNNER_NAME' --labels '$RUNNER_LABEL' --work _work"
unset TOKEN

cd "$RUNNER_DIR"
./svc.sh install joshan
./svc.sh start

SERVICE=$(systemctl list-unit-files --no-legend | awk '/actions\.runner\..*lifeos-pi5.*\.service/{print $1; exit}')
[[ -n "$SERVICE" ]] || fail 'runner systemd service not discovered after install'
systemctl is-active --quiet "$SERVICE" || fail 'runner service not active'

printf '%s\n' \
  'RESULT=PASS' \
  'GITHUB_RUNNER_BOOTSTRAPPED=YES' \
  "RUNNER_VERSION=$VERSION" \
  "RUNNER_NAME=$RUNNER_NAME" \
  "RUNNER_LABEL=$RUNNER_LABEL" \
  "RUNNER_SERVICE=$SERVICE" \
  'DEPLOY_GATEWAY=INSTALLED' \
  'NEXT_ACTION=dispatch LifeOS Pi Deploy audit-dispatcher-retirement workflow'
