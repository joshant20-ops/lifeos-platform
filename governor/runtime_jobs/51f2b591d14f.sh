#!/usr/bin/env bash
set -Eeuo pipefail

readonly JOB_ID=51f2b591d14f
readonly REPO="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
readonly BRANCH=engineer-self-observability-v1
readonly TEST_TIMEOUT_SECONDS=600
readonly GIT_TIMEOUT_SECONDS=180
WORKTREE=

fail() {
  local reason=${1:-unknown_failure}
  local status=${2:-1}
  printf 'OBSERVABILITY_PUBLICATION=FAIL reason=%s\n' "$reason" >&2
  printf 'RESULT=FAIL job=%s\n' "$JOB_ID" >&2
  exit "$status"
}

cleanup() {
  if [[ -n "$WORKTREE" ]]; then
    git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

command -v timeout >/dev/null || fail timeout_command_missing 20
command -v git >/dev/null || fail git_command_missing 21
command -v python3 >/dev/null || fail python3_command_missing 22
[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker 23
[[ -d "$REPO/.git" ]] || fail canonical_repository_missing 24
[[ -z "$(git -C "$REPO" status --porcelain)" ]] || fail canonical_repository_dirty 25

printf 'OBSERVABILITY_PUBLICATION=START branch=%s\n' "$BRANCH"

local_ref="refs/heads/$BRANCH"
remote_ref="refs/remotes/origin/$BRANCH"
has_local=false
git -C "$REPO" show-ref --verify --quiet "$local_ref" && has_local=true

# Pi5 is the canonical Git/network controller. Refresh only the requested
# feature ref; never reset main, force-push, or rewrite either branch. A fetch
# can legitimately fail when the local branch is precisely what needs its
# first publication; that case is allowed to continue to the normal push.
if timeout "$GIT_TIMEOUT_SECONDS" git -C "$REPO" fetch origin \
  "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"; then
  has_remote=true
else
  has_remote=false
  [[ "$has_local" == true ]] || fail feature_branch_unavailable_locally_and_remotely 30
  printf 'REMOTE_BRANCH=PENDING_FIRST_PUBLICATION branch=%s\n' "$BRANCH"
fi

if [[ "$has_local" == true ]]; then
  candidate="$local_ref"
  if [[ "$has_remote" == true ]] && \
     ! git -C "$REPO" merge-base --is-ancestor "$remote_ref" "$candidate"; then
    fail local_branch_does_not_contain_published_tip 31
  fi
else
  candidate="$remote_ref"
fi

candidate_sha=$(git -C "$REPO" rev-parse "$candidate")
WORKTREE=$(mktemp -d "/tmp/lifeos-${JOB_ID}.XXXXXX")
rmdir "$WORKTREE"
git -C "$REPO" worktree add --detach "$WORKTREE" "$candidate_sha" >/dev/null \
  || fail feature_worktree_creation_failed 32

required=(
  tests/test_engineer_job_observability_acceptance.py
  docs/architecture/engineer-self-improvement.md
)
for path in "${required[@]}"; do
  [[ -f "$WORKTREE/$path" ]] || fail "missing_acceptance_contract_${path//\//_}" 33
done

mapfile -t continuation_contracts < <(
  cd "$WORKTREE"
  git ls-files 'tests/*continuation*.py' | sort
)
(( ${#continuation_contracts[@]} > 0 )) || fail immediate_continuation_contract_missing 34

tests=(tests/test_engineer_job_observability_acceptance.py)
tests+=("${continuation_contracts[@]}")
printf 'TEST_ENVIRONMENT=PASS runner=python3_-m_pytest cwd=feature_worktree contracts=%s\n' "${#tests[@]}"
if ! (
  cd "$WORKTREE"
  PYTHONPATH="$WORKTREE${PYTHONPATH:+:$PYTHONPATH}" \
    timeout --signal=TERM --kill-after=15s "$TEST_TIMEOUT_SECONDS" \
    python3 -m pytest -q "${tests[@]}"
); then
  fail acceptance_tests_failed_or_timed_out 40
fi
printf 'ACCEPTANCE_CONTRACTS=PASS branch=%s sha=%s\n' "$BRANCH" "$candidate_sha"

# A normal push is deliberately used as the publication retry. It is a no-op
# when the remote already has this exact commit and fails closed on divergence.
if ! timeout "$GIT_TIMEOUT_SECONDS" git -C "$REPO" push origin \
  "$candidate_sha:refs/heads/$BRANCH"; then
  fail non_force_publication_retry_failed 50
fi

published_sha=$(timeout "$GIT_TIMEOUT_SECONDS" git -C "$REPO" ls-remote \
  --heads origin "$BRANCH" | awk 'NR == 1 {print $1}')
[[ "$published_sha" == "$candidate_sha" ]] || fail published_sha_mismatch 51

printf 'PUBLICATION_RETRY=PASS branch=%s sha=%s mode=non-force\n' "$BRANCH" "$published_sha"
printf 'OBSERVABILITY_PUBLICATION=PASS job=%s\n' "$JOB_ID"
printf 'RESULT=PASS job=%s\n' "$JOB_ID"
