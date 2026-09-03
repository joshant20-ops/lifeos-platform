#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
OWNER="${LIFEOS_REPO_OWNER:-joshan}"
GROUP="${LIFEOS_REPO_GROUP:-joshan}"

fail(){ echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || exec sudo -E bash "$0" "$@"
[[ -d "$REPO/.git" ]] || fail "missing repo: $REPO"
id "$OWNER" >/dev/null 2>&1 || fail "missing owner user: $OWNER"
getent group "$GROUP" >/dev/null 2>&1 || fail "missing group: $GROUP"

printf 'REPO_OWNERSHIP_REPAIR_VERSION=1\n'
printf 'repo=%s owner=%s group=%s\n' "$REPO" "$OWNER" "$GROUP"

printf '\n=== BEFORE ===\n'
stat -c 'index owner=%U group=%G mode=%a' "$REPO/.git/index" 2>/dev/null || true
find "$REPO/.git" \( ! -user "$OWNER" -o ! -group "$GROUP" \) -printf '%u:%g %m %p\n' | head -100 || true

# The repository checkout is owned by joshan. Git metadata created by root-run
# deployment scripts must never remain root-owned, otherwise normal fetch/reset
# fails. Repair ownership only inside this checkout.
chown -R "$OWNER:$GROUP" "$REPO/.git"

# Repair the specific worktree paths previously observed as root-owned. These
# are either tracked files or generated cache/staging paths inside this repo.
for path in \
  "$REPO/architecture/decisions/pa-audit-retirement.md" \
  "$REPO/homelab/live/usr/local/lib/__pycache__" \
  "$REPO/staged" \
  "$REPO/tests/__pycache__"
do
  [[ -e "$path" ]] && chown -R "$OWNER:$GROUP" "$path"
done

printf '\n=== VERIFY ===\n'
remaining_git=$(find "$REPO/.git" \( ! -user "$OWNER" -o ! -group "$GROUP" \) -print -quit)
[[ -z "$remaining_git" ]] || fail "non-$OWNER ownership remains under .git: $remaining_git"

runuser -u "$OWNER" -- git -C "$REPO" status --short --branch
runuser -u "$OWNER" -- git -C "$REPO" update-index --refresh >/dev/null

printf '\nRESULT=PASS\nREPO_GIT_OWNERSHIP=%s:%s\nNORMAL_GIT_ACCESS=RESTORED\nMUTATIONS=OWNERSHIP_ONLY\n' "$OWNER" "$GROUP"
