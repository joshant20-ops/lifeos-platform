#!/usr/bin/env bash
set -Eeuo pipefail

JOBS_REPO="${LIFEOS_JOBS_REPO:-/home/joshan/lifeos-jobs}"
PLATFORM_REPO="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"

echo "==> LifeOS jobs auth diagnostic"

[[ "$(hostname)" == "Docker" ]] || { echo "RESULT=BLOCKED"; echo "REASON=wrong_host"; exit 20; }
[[ -d "$JOBS_REPO/.git" ]] || { echo "RESULT=BLOCKED"; echo "REASON=jobs_repo_missing"; exit 21; }
[[ -d "$PLATFORM_REPO/.git" ]] || { echo "RESULT=BLOCKED"; echo "REASON=platform_repo_missing"; exit 22; }

printf '\n=== REPOSITORY STATE ===\n'
git -C "$JOBS_REPO" status --short --branch
printf 'origin='; git -C "$JOBS_REPO" remote get-url origin
printf 'head='; git -C "$JOBS_REPO" rev-parse --short HEAD
printf 'origin_main='; git -C "$JOBS_REPO" rev-parse --short origin/main 2>/dev/null || echo unknown

printf '\n=== SSH CLIENT CONFIG (sanitised) ===\n'
ssh -G git@github.com 2>/dev/null | awk '
  $1=="hostname" || $1=="user" || $1=="port" || $1=="identityfile" || $1=="identitiesonly" {print}
' || true

printf '\n=== SSH MATERIAL METADATA ONLY ===\n'
if [[ -d /home/joshan/.ssh ]]; then
  find /home/joshan/.ssh -maxdepth 1 -type f -printf '%f mode=%m bytes=%s\n' 2>/dev/null | sort
else
  echo '.ssh directory absent'
fi

printf '\n=== SSH AGENT IDENTITIES ===\n'
if ssh-add -l >/tmp/lifeos-ssh-agent.$$ 2>&1; then
  sed -E 's#(/[^ ]+)+##g' /tmp/lifeos-ssh-agent.$$ || true
else
  cat /tmp/lifeos-ssh-agent.$$ || true
fi
rm -f /tmp/lifeos-ssh-agent.$$

printf '\n=== GITHUB SSH AUTH PROBE ===\n'
set +e
AUTH_OUT="$(timeout 12s ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new git@github.com 2>&1)"
AUTH_RC=$?
set -e
# GitHub normally returns rc=1 even on successful authentication; print only its standard identity message.
printf '%s\n' "$AUTH_OUT" | sed -n '1,6p'
printf 'ssh_probe_rc=%s\n' "$AUTH_RC"

printf '\n=== FETCH PROBE ===\n'
set +e
git -C "$JOBS_REPO" fetch --dry-run origin main >/tmp/lifeos-jobs-fetch.$$ 2>&1
FETCH_RC=$?
set -e
cat /tmp/lifeos-jobs-fetch.$$ || true
rm -f /tmp/lifeos-jobs-fetch.$$
printf 'fetch_rc=%s\n' "$FETCH_RC"

printf '\n=== NON-MUTATING WRITE-AUTH PROBE ===\n'
# git push --dry-run exercises receive-pack authentication without updating refs.
set +e
git -C "$JOBS_REPO" push --dry-run origin HEAD:main >/tmp/lifeos-jobs-push.$$ 2>&1
PUSH_RC=$?
set -e
cat /tmp/lifeos-jobs-push.$$ || true
rm -f /tmp/lifeos-jobs-push.$$
printf 'push_dry_run_rc=%s\n' "$PUSH_RC"

printf '\n=== CLASSIFICATION ===\n'
if [[ "$PUSH_RC" -eq 0 ]]; then
  echo 'RESULT=PASS'
  echo 'JOBS_WRITE_AUTH=WORKING'
elif printf '%s' "$AUTH_OUT" | grep -qi 'successfully authenticated'; then
  echo 'RESULT=BLOCKED'
  echo 'JOBS_WRITE_AUTH=AUTHENTICATED_BUT_PUSH_FAILED'
else
  echo 'RESULT=BLOCKED'
  echo 'JOBS_WRITE_AUTH=SSH_IDENTITY_NOT_ACCEPTED'
fi

echo 'MUTATIONS=NONE'
