#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPOSITORY=joshant20-ops/lifeos-platform
readonly ISSUE=1
readonly PR_TITLE='chore: repository foundation'
readonly SELF=governor/runtime_jobs/242407bcc655.sh

emit() {
  printf '%s\n' \
    "ISSUE_VALIDITY=$1" \
    "LIFEOS_WORK_STATE=$2" \
    "BARRIER=$3" \
    "NEXT_AUTONOMOUS_ACTION=$4" \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    "RESULT=$5" \
    "TESTS=$6" \
    "NEXT_RUNTIME_CHECK=$7"
}

fail() {
  local barrier=$1
  printf 'FAIL=%s\n' "$barrier" >&2
  emit VALID BLOCKED "$barrier" \
    "resolve $barrier on Pi5 and rerun $SELF through Watchman" \
    RETRY 'foundation publication checks failed closed' "$SELF"
  exit 1
}

run() { timeout --signal=TERM --kill-after=10s "$@"; }

for tool in git gh jq timeout; do
  command -v "$tool" >/dev/null || fail "missing_$tool"
done

root=$(run 10s git rev-parse --show-toplevel) || fail repository_root_unreadable
cd "$root"

required=(
  README.md
  AGENTS.md
  docs/architecture_overview.md
  docs/roadmap.md
  docs/migration_strategy.md
  .github/copilot-instructions.md
  bootstrap/README.md
  governance/communication.md
)
for path in "${required[@]}"; do
  [[ -f "$path" && ! -L "$path" && -s "$path" ]] || fail "required_file_invalid_$path"
done

branch=$(run 10s git symbolic-ref --quiet --short HEAD) || fail review_branch_missing
[[ "$branch" != main && "$branch" != master ]] || fail review_branch_is_default
[[ -z $(run 10s git status --porcelain --untracked-files=no) ]] || fail canonical_checkout_dirty

origin=$(run 10s git remote get-url origin) || fail canonical_origin_missing
normalized=${origin%.git}
normalized=${normalized/github.com:/github.com/}
[[ "$normalized" == *"github.com/$REPOSITORY" ]] || fail canonical_origin_mismatch

issue_state=$(run 30s gh issue view "$ISSUE" --repo "$REPOSITORY" --json state --jq .state) || fail issue_lookup_failed
if [[ "$issue_state" != OPEN ]]; then
  emit ALREADY_COMPLETE PASS none \
    'retain the closed issue and its review evidence' \
    PASS 'required files valid; issue is already closed' none
  exit 0
fi

# GitHub exposes Copilot's coding agent through this bot login for issue
# assignment. The operation is idempotent when it is already assigned.
run 30s gh issue edit "$ISSUE" --repo "$REPOSITORY" \
  --add-assignee 'copilot-swe-agent[bot]' >/dev/null || fail copilot_assignment_failed
assignees=$(run 30s gh issue view "$ISSUE" --repo "$REPOSITORY" \
  --json assignees --jq '.assignees[].login') || fail copilot_assignment_verification_failed
grep -Fxq 'copilot-swe-agent[bot]' <<<"$assignees" || fail copilot_assignment_not_observed
printf 'COPILOT_ASSIGNMENT=PASS issue=%s\n' "$ISSUE"

pr_json=$(run 30s gh pr list --repo "$REPOSITORY" --head "$branch" --state open \
  --json number,title,isDraft --limit 1) || fail pull_request_lookup_failed
pr_number=$(jq -r '.[0].number // empty' <<<"$pr_json") || fail pull_request_response_invalid
if [[ -z "$pr_number" ]]; then
  run 120s git push --set-upstream origin "$branch" || fail review_branch_push_failed
  run 60s gh pr create --repo "$REPOSITORY" --head "$branch" --base main \
    --draft --title "$PR_TITLE" \
    --body 'Implements #1. Adds and validates the governed repository foundation for independent review.' \
    >/dev/null || fail draft_pull_request_creation_failed
  pr_number=$(run 30s gh pr view "$branch" --repo "$REPOSITORY" --json number --jq .number) \
    || fail created_pull_request_lookup_failed
fi

pr_title=$(run 30s gh pr view "$pr_number" --repo "$REPOSITORY" --json title --jq .title) \
  || fail pull_request_title_lookup_failed
pr_draft=$(run 30s gh pr view "$pr_number" --repo "$REPOSITORY" --json isDraft --jq .isDraft) \
  || fail pull_request_draft_lookup_failed
[[ "$pr_title" == "$PR_TITLE" ]] || fail pull_request_title_mismatch
[[ "$pr_draft" == true ]] || fail pull_request_not_draft
printf 'DRAFT_PULL_REQUEST=PASS number=%s title=%s\n' "$pr_number" "$pr_title"

emit VALID PASS none \
  'await independent Auditor review of the draft pull request' \
  PASS '8 required files, Copilot assignment, review branch, and draft pull request PASS' none
