#!/usr/bin/env bash
set -euo pipefail

STATE_DIR=${LIFEOS_AGENT_STATE:-/var/lib/lifeos-agent}
JOBS_REPO=${LIFEOS_JOBS_REPO:-/home/joshan/lifeos-jobs}
OUT_DIR="$JOBS_REPO/jobs"

[[ -d "$JOBS_REPO/.git" ]] || {
  echo "RESULT=BLOCKED"
  echo "REASON=lifeos_jobs_repo_missing path=$JOBS_REPO"
  exit 30
}

mkdir -p "$OUT_DIR"

python3 - "$STATE_DIR" "$OUT_DIR" <<'PY'
import json
import pathlib
import sys

state = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])

for path in sorted(state.glob('*.json')):
    try:
        job = json.loads(path.read_text())
    except Exception:
        continue

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
        'request': job.get('request'),
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
PY

cd "$JOBS_REPO"
git fetch origin main >/dev/null 2>&1 || true
git add jobs

if git diff --cached --quiet; then
  echo "RESULT=PASS"
  echo "JOBS_EXPORT=no_change"
  exit 0
fi

git diff --cached --check
git commit -m "jobs: export sanitised LifeOS job records" >/dev/null
git push origin HEAD:main >/dev/null

echo "RESULT=PASS"
echo "JOBS_EXPORT=updated"
