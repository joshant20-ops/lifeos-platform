#!/usr/bin/env bash
set -euo pipefail

OWNER=${LIFEOS_GITHUB_OWNER:-joshant20-ops}

command -v gh >/dev/null || {
  echo "RESULT=BLOCKED"
  echo "REASON=gh_cli_required"
  exit 30
}

gh auth status >/dev/null

create_repo() {
  local name=$1 description=$2
  if gh repo view "$OWNER/$name" >/dev/null 2>&1; then
    echo "$name=EXISTS"
    return
  fi
  gh repo create "$OWNER/$name" --private --description "$description" --add-readme
  echo "$name=CREATED"
}

create_repo lifeos-jobs "LifeOS sanitised engineering job history and audit trail"
create_repo lifeos-snapshots "LifeOS private sanitised observed-state snapshots and drift evidence"

# Add authority READMEs without putting operational evidence into the bootstrap host.
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for repo in lifeos-jobs lifeos-snapshots; do
  gh repo clone "$OWNER/$repo" "$TMP/$repo" -- --quiet
  cd "$TMP/$repo"
  git config user.name "LifeOS Bootstrap"
  git config user.email "lifeos-bootstrap@localhost"

done

cat >"$TMP/lifeos-jobs/README.md" <<'EOF'
# lifeos-jobs

Private durable engineering audit history for LifeOS.

This repository is **not the live queue**. Live locks, stages and RUNNING state remain on the Pi5 under `/var/lib/lifeos-agent`.

Only sanitised job records are committed here. Raw runtime evidence, secrets, credentials, private documents, Home Assistant history and other personal data are forbidden.

Authority: audit/history only. This repository never defines desired deployable state.
EOF

cat >"$TMP/lifeos-snapshots/README.md" <<'EOF'
# lifeos-snapshots

Private sanitised observed-state evidence for LifeOS.

Contains hashes, service/container health and drift metadata only. It must never contain secrets, credentials, private documents, raw Home Assistant history or arbitrary logs.

Authority: evidence only. Snapshot content may report drift but must never overwrite, restore, seed or otherwise mutate `lifeos-platform`.
EOF

for repo in lifeos-jobs lifeos-snapshots; do
  cd "$TMP/$repo"
  git add README.md
  if ! git diff --cached --quiet; then
    git commit -m "docs: define repository authority" >/dev/null
    git push origin HEAD:main >/dev/null
  fi
done

echo "RESULT=PASS"
echo "DESIRED_STATE=$OWNER/lifeos-platform"
echo "JOB_HISTORY=$OWNER/lifeos-jobs"
echo "OBSERVED_STATE=$OWNER/lifeos-snapshots"
echo "VISIBILITY=private_for_jobs_and_snapshots"
