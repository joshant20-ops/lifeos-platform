#!/usr/bin/env bash
set -Eeuo pipefail

# #759 direct OpenHands isolation proof.
# Deliberately bypasses Governor autonomous job submission, milestone decisions,
# publication, archive and issue disposition. lifeos-local-builder is retained
# only as the thin Tower/Engineer/local-model transport into OpenHands.
job_id="direct-openhands-${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-1}"
marker="OPENHANDS_DIRECT_ACTION_${GITHUB_RUN_ID:-manual}_${GITHUB_RUN_ATTEMPT:-1}"
runtime_path="governor/runtime_jobs/${job_id}.sh"
request="Direct OpenHands isolation test. Create ${runtime_path} in the disposable worktree with exactly three lines: #!/usr/bin/env bash ; set -euo pipefail ; printf '%s\\n' '${marker}'. Execute it and verify stdout is exactly ${marker}. Change no other file. Do not commit, push, fetch, clone, or access GitHub. Stop when the task and test are complete."

log=$(mktemp)
runtime=$(mktemp)
trap 'rm -f "$log" "$runtime"' EXIT
echo 'OPENHANDS_DIRECT_TEST=START'
set +e
LIFEOS_JOB_ID="$job_id" LIFEOS_JOB_TASK_CLASS=normal LIFEOS_JOB_PRIVACY=local-only \
  /usr/local/libexec/lifeos-local-builder "$request" 1 '' | tee "$log"
rc=${PIPESTATUS[0]}
set -e
echo "OPENHANDS_DIRECT_BUILDER_RC=$rc"
test "$rc" -eq 0
grep -q '^AGENT_SESSION=openhands provider=governor-broker-local-only$' "$log"
grep -q '^HANDOFF_BASE=' "$log"
b64=$(sed -n 's/^HANDOFF_RUNTIME_B64=//p' "$log" | tail -1)
test -n "$b64"
printf '%s' "$b64" | base64 -d >"$runtime"
python3 - "$runtime" "$marker" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1]); marker=sys.argv[2]
expected=["#!/usr/bin/env bash", "set -euo pipefail", f"printf '%s\\n' '{marker}'"]
actual=p.read_text().splitlines()
assert actual == expected, repr(actual)
print("OPENHANDS_DIRECT_FILE_ASSERTION=PASS")
PY
chmod 700 "$runtime"
test "$("$runtime")" = "$marker"
echo 'OPENHANDS_DIRECT_EXECUTION_ASSERTION=PASS'
echo 'OPENHANDS_DIRECT_GOVERNOR_JOB_BYPASS=PASS'
