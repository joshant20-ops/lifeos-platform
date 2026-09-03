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

runner_service() {
  local unit
  unit=$(systemctl list-unit-files --type=service --all --no-legend --no-pager --full 2>/dev/null \
    | awk '/^actions\.runner\..*lifeos-pi5.*\.service[[:space:]]/{print $1; exit}')
  if [[ -z "$unit" ]]; then
    local path
    path=$(find /etc/systemd/system -maxdepth 1 -type f -name 'actions.runner.*lifeos-pi5*.service' -print -quit 2>/dev/null || true)
    [[ -z "$path" ]] || unit=${path##*/}
  fi
  printf '%s' "$unit"
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo'
[[ "$(uname -m)" == aarch64 || "$(uname -m)" == arm64 ]] || fail 'runner bootstrap requires ARM64 host'

cd "$PLATFORM"
HEAD=$(runj git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runj git -C "$PLATFORM" rev-parse origin/main)
STATUS=$(runj git -C "$PLATFORM" status --porcelain)
[[ "$HEAD" == "$ORIGIN" ]] || fail 'platform HEAD must equal origin/main'
[[ -z "$STATUS" ]] || fail 'platform worktree must be clean'

# Refresh the narrow privilege gateway on every bootstrap invocation. This is
# intentionally independent of runner registration so newly allow-listed
# operations cannot be blocked by a stale root-owned gateway copy.
bash "$PLATFORM/scripts/lifeos-install-github-runner-gateway.sh"

SERVICE=$(runner_service)
if [[ -n "$SERVICE" ]]; then
  systemctl daemon-reload
  systemctl enable --now "$SERVICE" >/dev/null
  systemctl is-active --quiet "$SERVICE" || fail 'existing runner service is not active'
  echo 'RUNNER_SERVICE_ALREADY_PRESENT=YES'
  echo "RUNNER_SERVICE=$SERVICE"
  systemctl --no-pager --full status "$SERVICE" | head -25 || true
  echo 'RESULT=PASS'
  echo 'GITHUB_RUNNER_BOOTSTRAPPED=ALREADY_PRESENT'
  echo 'DEPLOY_GATEWAY=REFRESHED'
  exit 0
fi

# A configured runner without a discoverable service is recoverable: reinstall
# only its systemd service. Do not request another registration token or replace
# the GitHub runner registration.
if [[ -f "$RUNNER_DIR/.runner" ]]; then
  [[ -x "$RUNNER_DIR/svc.sh" ]] || fail 'runner is configured but svc.sh is missing'
  echo 'RUNNER_REGISTRATION_ALREADY_PRESENT=YES'
  cd "$RUNNER_DIR"
  ./svc.sh install joshan
  ./svc.sh start
  systemctl daemon-reload
  SERVICE=$(runner_service)
  [[ -n "$SERVICE" ]] || fail 'runner service not discovered after recovery install'
  systemctl enable --now "$SERVICE" >/dev/null
  systemctl is-active --quiet "$SERVICE" || fail 'recovered runner service is not active'
  printf '%s\n' \
    'RESULT=PASS' \
    'GITHUB_RUNNER_BOOTSTRAPPED=RECOVERED_SERVICE' \
    "RUNNER_NAME=$RUNNER_NAME" \
    "RUNNER_LABEL=$RUNNER_LABEL" \
    "RUNNER_SERVICE=$SERVICE" \
    'DEPLOY_GATEWAY=REFRESHED' \
    'NEXT_ACTION=dispatch LifeOS Pi deployment workflow'
  exit 0
fi

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
systemctl daemon-reload

SERVICE=$(runner_service)
[[ -n "$SERVICE" ]] || fail 'runner systemd service not discovered after install'
systemctl enable --now "$SERVICE" >/dev/null
systemctl is-active --quiet "$SERVICE" || fail 'runner service not active'

printf '%s\n' \
  'RESULT=PASS' \
  'GITHUB_RUNNER_BOOTSTRAPPED=YES' \
  "RUNNER_VERSION=$VERSION" \
  "RUNNER_NAME=$RUNNER_NAME" \
  "RUNNER_LABEL=$RUNNER_LABEL" \
  "RUNNER_SERVICE=$SERVICE" \
  'DEPLOY_GATEWAY=INSTALLED' \
  'NEXT_ACTION=dispatch LifeOS Pi deployment workflow'
