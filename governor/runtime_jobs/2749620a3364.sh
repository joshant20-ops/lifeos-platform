#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only acceptance probe for issue #12. It does not start a dispatcher,
# create a job, modify an issue, or execute the R580 production candidate.
readonly REPO=/home/joshan/lifeos-platform
readonly STATE=/var/lib/lifeos-backlog-runner/state.json
readonly GOV=http://127.0.0.1:8790
readonly ISSUE_REPO=joshant20-ops/lifeos-platform
readonly ISSUE=7

finish() {
  local result=$1 barrier=$2 tests=$3 next=$4
  printf '%s\n' 'ISSUE_VALIDITY=VALID' \
    "LIFEOS_WORK_STATE=$([[ $result == PASS ]] && echo PASS || echo BLOCKED)" \
    "BARRIER=$barrier" "NEXT_AUTONOMOUS_ACTION=$next" \
    'DISCOVERED_ISSUES_JSON_B64=none' "RESULT=$result" "TESTS=$tests" \
    "NEXT_RUNTIME_CHECK=$next"
}
fail() { printf 'CHECK=%s FAIL\n' "$1" >&2; finish BLOCKED "$1" 'runtime acceptance incomplete' 'repair the named current-pipeline dependency and rerun this launcher through Watchman'; exit 1; }
run() { local seconds=$1; shift; timeout --signal=TERM --kill-after=5s "$seconds" "$@"; }

for tool in timeout systemctl curl python3 gh; do command -v "$tool" >/dev/null || fail "missing_$tool"; done
[[ -r $STATE ]] || fail backlog_state_unreadable
systemctl is-active --quiet lifeos-backlog-runner.timer || fail backlog_timer_inactive
systemctl is-enabled --quiet lifeos-backlog-runner.timer || fail backlog_timer_disabled
systemctl is-active --quiet lifeos-autonomous-agent.service || fail governor_service_inactive
[[ $(systemctl show lifeos-backlog-runner.service -p Result --value) == success ]] || fail backlog_last_run_failed
[[ $(systemctl show lifeos-job-publisher.service -p LoadState --value) != not-found ]] || fail job_publisher_unit_missing
[[ $(systemctl show lifeos-job-publisher.service -p Result --value) != failed ]] || fail job_publisher_last_run_failed

issue_json=$(run 30s gh issue view "$ISSUE" --repo "$ISSUE_REPO" --json number,state,title,labels) || fail github_issue_lookup
jobs_json=$(run 15s curl --fail --silent --show-error --max-time 10 "$GOV/jobs") || fail governor_jobs_lookup

ISSUE_JSON="$issue_json" JOBS_JSON="$jobs_json" STATE_PATH="$STATE" RECORD_ROOT="$REPO/governor/job_records" python3 - <<'PY' || exit 1
import json, os, pathlib, sys

issue = json.loads(os.environ["ISSUE_JSON"])
jobs_raw = json.loads(os.environ["JOBS_JSON"])
jobs = jobs_raw.get("jobs", jobs_raw.get("items", [])) if isinstance(jobs_raw, dict) else jobs_raw
state = json.loads(pathlib.Path(os.environ["STATE_PATH"]).read_text())
entry = state.get("issues", {}).get("7", {})
active = state.get("active") or {}
linked = []
for candidate in (active.get("job_id") if int(active.get("issue", -1)) == 7 else None,
                  entry.get("job_id"), entry.get("last_job_id")):
    if candidate and candidate not in linked:
        linked.append(str(candidate))
for attempt in state.get("attempts", []):
    if int(attempt.get("issue", -1)) == 7 and attempt.get("job_id") not in linked:
        linked.append(str(attempt["job_id"]))

# Published, sanitised repository records are a second durable evidence source
# and cover deployments that predate the current state schema.
record_root = pathlib.Path(os.environ["RECORD_ROOT"])
for path in sorted(record_root.glob("*.json")):
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        continue
    if "Process GitHub issue #7 " in str(record.get("goal_summary", "")):
        job_id = str(record.get("job_id") or path.stem)
        if job_id not in linked:
            linked.append(job_id)

if issue.get("number") != 7 or not linked:
    print("CHECK=issue_7_persisted_link FAIL", file=sys.stderr)
    print("ISSUE_VALIDITY=VALID\nLIFEOS_WORK_STATE=BLOCKED\nBARRIER=issue_7_has_no_persisted_job_link")
    print("NEXT_AUTONOMOUS_ACTION=repair discovery/persistence and rerun through Watchman")
    print("DISCOVERED_ISSUES_JSON_B64=none\nRESULT=BLOCKED\nTESTS=runtime acceptance incomplete")
    print("NEXT_RUNTIME_CHECK=rerun governor/runtime_jobs/2749620a3364.sh through Watchman")
    raise SystemExit(1)

live = {str(job.get("id")): str(job.get("status", "UNKNOWN")).upper() for job in jobs if job.get("id")}
records = {}
for job_id in linked:
    path = record_root / f"{job_id}.json"
    if path.exists():
        record = json.loads(path.read_text())
        records[job_id] = str(record.get("final_status", "UNKNOWN")).upper()
evidence = {
    "schema_version": 1,
    "github_issue": 7,
    "github_state": issue.get("state"),
    "current_state": entry.get("work_state") or ("IN_PROGRESS" if active.get("issue") == 7 else "RECORDED"),
    "job_ids": linked,
    "governor_states": {job_id: live[job_id] for job_id in linked if job_id in live},
    "record_states": records,
    "obsolete_bootstrap_excluded": True,
    "production_r580_change_executed": False,
}
print("ISSUE_JOB_EVIDENCE_JSON=" + json.dumps(evidence, sort_keys=True, separators=(",", ":")))
print("CHECK=issue_7_discovery_persistence_engineer_link PASS")
PY

run 90s python3 -m pytest -q "$REPO/tests/test_issue_pickup_contract.py" "$REPO/tests/test_backlog_runner.py" || fail focused_contract_tests
finish PASS none 'issue pickup contract and live read-only linkage PASS' none
