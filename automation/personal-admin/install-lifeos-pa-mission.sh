#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
SRC="$REPO/automation/personal-admin/lifeos-pa-mission.py"
DEST="$HOME/.local/bin/lifeos-pa-mission"
STATE="$HOME/.local/state/lifeos-pa-autonomy"

cd "$REPO"
test -f "$SRC"
python3 -m py_compile "$SRC"
install -d -m 0755 "$HOME/.local/bin"
install -d -m 0700 "$STATE"
install -m 0755 "$SRC" "$DEST"

test -x "$DEST"
"$DEST" --help >/dev/null

echo "LIFEOS_PA_RUNNER_INSTALL=PASS"
echo "LIFEOS_PA_RUNNER=$DEST"
echo "LIFEOS_PA_STATE=$STATE"
