#!/usr/bin/env bash
set -euo pipefail

OWNER=${LIFEOS_GITHUB_OWNER:-joshant20-ops}
HOME_DIR=${HOME:-/home/joshan}
PLATFORM=${LIFEOS_PLATFORM_REPO:-$HOME_DIR/lifeos-platform}
JOBS=$HOME_DIR/lifeos-jobs
SNAPSHOTS=$HOME_DIR/lifeos-snapshots

[[ "$(hostname)" == "Docker" ]] || {
  echo "RESULT=BLOCKED"
  echo "REASON=must_run_on_Docker"
  exit 20
}

clone_or_update() {
  local repo=$1 path=$2
  if [[ -d "$path/.git" ]]; then
    git -C "$path" fetch origin main
    git -C "$path" reset --hard origin/main
  else
    git clone "git@github.com:$OWNER/$repo.git" "$path"
  fi
}

clone_or_update lifeos-jobs "$JOBS"
clone_or_update lifeos-snapshots "$SNAPSHOTS"

chmod +x \
  "$PLATFORM/governor/scripts/export-lifeos-job-records.sh" \
  "$PLATFORM/governor/scripts/snapshot-lifeos-observed-state.sh"

LIFEOS_JOBS_REPO="$JOBS" \
  "$PLATFORM/governor/scripts/export-lifeos-job-records.sh"

LIFEOS_SNAPSHOTS_REPO="$SNAPSHOTS" \
LIFEOS_PLATFORM_REPO="$PLATFORM" \
LIFEOS_HOST_ROLE=pi5-controller \
  "$PLATFORM/governor/scripts/snapshot-lifeos-observed-state.sh"

echo "RESULT=PASS"
echo "PLATFORM=$PLATFORM"
echo "JOBS=$JOBS"
echo "SNAPSHOTS=$SNAPSHOTS"
echo "LIVE_QUEUE=/var/lib/lifeos-agent"
echo "AUTHORITY=platform_only"
