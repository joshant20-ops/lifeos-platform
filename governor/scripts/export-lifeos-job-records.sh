#!/usr/bin/env bash
set -euo pipefail

STATE_DIR=${LIFEOS_AGENT_STATE:-/var/lib/lifeos-agent}
JOBS_REPO=${LIFEOS_JOBS_REPO:-/home/joshan/lifeos-jobs}
JOB_ID_FILTER=${LIFEOS_JOB_ID_FILTER:-}
EXPORT_ROOT=$(mktemp -d)
EXPORT_WORKTREE="$EXPORT_ROOT/repo"

cleanup() {
  git -C "$JOBS_REPO" worktree remove --force "$EXPORT_WORKTREE" >/dev/null 2>&1 || true
  rm -rf -- "$EXPORT_ROOT"
}
trap cleanup EXIT

if [[ -n "$JOB_ID_FILTER" && ! "$JOB_ID_FILTER" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
  echo "RESULT=BLOCKED"
  echo "REASON=invalid_job_id_filter"
  exit 30
fi

[[ -d "$JOBS_REPO/.git" ]] || {
  echo "RESULT=BLOCKED"
  echo "REASON=lifeos_jobs_repo_missing path=$JOBS_REPO"
  exit 30
}

# Use FETCH_HEAD as the authoritative snapshot. The persistent checkout's
# remote-tracking refs may legitimately be stale or locally divergent.
git -C "$JOBS_REPO" fetch origin refs/heads/main >/dev/null
REMOTE_MAIN=$(git -C "$JOBS_REPO" rev-parse FETCH_HEAD)
git -C "$JOBS_REPO" worktree add --detach "$EXPORT_WORKTREE" "$REMOTE_MAIN" >/dev/null
OUT_DIR="$EXPORT_WORKTREE/jobs"
mkdir -p "$OUT_DIR"

python3 - "$STATE_DIR" "$OUT_DIR" "$JOB_ID_FILTER" <<'PY'
import json
import pathlib
import sys

state = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
job_filter = sys.argv[3]
matched = False

for path in sorted(state.glob('*.json')):
    try:
        job = json.loads(path.read_text())
    except Exception:
        continue
    if job_filter and str(job.get('id') or '') != job_filter:
        continue
    matched = True

    iterations = []
    platform_commits = []
    for rec in job.get('iterations') or []:
        verification = rec.get('verification') or {}
        evidence = str(rec.get('evidence') or '')
        for line in evidence.splitlines():
            if line.startswith('PI5_COMMIT='):
                platform_commits.append(line.split('=', 1)[1].strip())
        iterations.append({
            'iteration': rec.get('iteration'),
            'started_at': rec.get('started_at'),
            'finished_at': rec.get('finished_at'),
            'builder_rc': rec.get('builder_rc'),
            'verdict': verification.get('verdict'),
            'reason': verification.get('reason'),
            'next_instruction': verification.get('next_instruction'),
            'failure_signature': rec.get('failure_signature'),
        })

    safe = {
        'schema_version': 1,
        'id': job.get('id'),
        'request': (
            '[LOCAL-ONLY REQUEST REDACTED]'
            if job.get('privacy') == 'local-only'
            else job.get('request')
        ),
        'privacy': job.get('privacy'),
        'created_at': job.get('created_at'),
        'started_at': job.get('started_at'),
        'completed_at': job.get('completed_at'),
        'status': job.get('status'),
        'stage': job.get('stage'),
        'blocked_reason': job.get('blocked_reason'),
        'retry_of': job.get('retry_of'),
        'repeated_failure_count': job.get('repeated_failure_count'),
        'platform_commits': list(dict.fromkeys(platform_commits)),
        'iterations': iterations,
    }

    # Never export raw evidence or any unknown fields from local job state.
    target = out / f"{safe['id']}.json"
    target.write_text(json.dumps(safe, indent=2, sort_keys=True) + '\n')

if job_filter and not matched:
    raise SystemExit("requested_job_record_not_found")
PY

git -C "$EXPORT_WORKTREE" add jobs

if git -C "$EXPORT_WORKTREE" diff --cached --quiet; then
  [[ -z "$JOB_ID_FILTER" ]] || git -C "$EXPORT_WORKTREE" cat-file -e "HEAD:jobs/$JOB_ID_FILTER.json"
  # A no-change export still proves REMOTE_MAIN contains the requested
  # record; synchronize the conventional tracking ref for downstream readers.
  git -C "$JOBS_REPO" update-ref refs/remotes/origin/main "$REMOTE_MAIN"
  echo "RESULT=PASS"
  echo "JOBS_EXPORT=no_change"
  [[ -z "$JOB_ID_FILTER" ]] || echo "JOBS_EXPORT_JOB_ID=$JOB_ID_FILTER"
  exit 0
fi

git -C "$EXPORT_WORKTREE" diff --cached --check
git -C "$EXPORT_WORKTREE" -c user.name=lifeos-job-exporter -c user.email=lifeos@localhost \
  commit -m "jobs: export sanitised LifeOS job records" >/dev/null
git -C "$EXPORT_WORKTREE" push origin HEAD:main >/dev/null
remote_head=$(git -C "$JOBS_REPO" ls-remote origin refs/heads/main | awk '{print $1}')
test -n "$remote_head"
test "$(git -C "$EXPORT_WORKTREE" rev-parse HEAD)" = "$remote_head"
# Keep the persistent checkout's conventional tracking ref coherent for
# downstream readers, while remote truth remains verified via ls-remote.
git -C "$JOBS_REPO" update-ref refs/remotes/origin/main "$remote_head"

echo "RESULT=PASS"
echo "JOBS_EXPORT=updated"
[[ -z "$JOB_ID_FILTER" ]] || echo "JOBS_EXPORT_JOB_ID=$JOB_ID_FILTER"
