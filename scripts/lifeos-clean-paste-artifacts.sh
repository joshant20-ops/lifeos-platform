#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="${LIFEOS_BACKUP_ROOT:-/mnt/docker-data/automation/backups/paste-artifacts-${STAMP}}"

say(){ printf '\n==> %s\n' "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
gate(){ local a; printf '\nGATE: %s\nType EXACTLY '\''YES'\'' to continue: ' "$1"; read -r a; [[ "$a" == YES ]] || die "Gate declined."; }

[[ $EUID -eq 0 ]] || exec sudo -E bash "$0" "$@"
[[ -d "$REPO/.git" ]] || die "Repository missing: $REPO"
cd "$REPO"

say "LifeOS paste-artifact cleanup"
mapfile -t UNTRACKED < <(git status --porcelain=v1 -z | python3 -c 'import sys; d=sys.stdin.buffer.read().split(b"\0"); [print(x[3:].decode("utf-8","surrogateescape")) for x in d if x.startswith(b"?? ")]')

if ((${#UNTRACKED[@]} == 0)); then
  echo "RESULT=PASS"
  echo "UNTRACKED=0"
  exit 0
fi

printf 'Untracked paths found:\n'
for p in "${UNTRACKED[@]}"; do printf '  %q\n' "$p"; done

# Fail closed unless every untracked path looks like shell/pager paste debris.
for p in "${UNTRACKED[@]}"; do
  base="$(basename -- "$p")"
  case "$base" in
    *"grep"*|*"lifeos"*|*"job"*|*"true"*|*"echo"*|*"||"*|*"'"*|*'"'*|*"|"*) ;;
    *) die "Untracked path does not look like known paste debris: $p" ;;
  esac
done

gate "All untracked paths look like paste debris. Move them to a recovery bundle?"
mkdir -p "$BACKUP"
for p in "${UNTRACKED[@]}"; do
  [[ -e "$p" || -L "$p" ]] || die "Path vanished during cleanup: $p"
  dest="$BACKUP/$(basename -- "$p")"
  # Avoid collisions safely.
  n=0
  while [[ -e "$dest" ]]; do n=$((n+1)); dest="$BACKUP/$(basename -- "$p").$n"; done
  mv -- "$p" "$dest"
done

if [[ -n "$(git status --porcelain)" ]]; then
  git status --short
  die "Repository is still dirty after removing paste debris."
fi

printf '\nRESULT=PASS\nREPO_CLEAN=true\nBACKUP=%s\n' "$BACKUP"
