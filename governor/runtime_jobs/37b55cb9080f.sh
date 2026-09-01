#!/usr/bin/env bash
set -Eeuo pipefail

readonly AGENT_URL=${LIFEOS_AGENT_URL:-http://127.0.0.1:8790}
readonly PLATFORM=${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}
readonly REQUEST='Issue 14 fresh privacy-classifier probe v1: Perform a read-only Engineer audit of repository code and documentation for consistency. This is ordinary engineering work using only cloud-safe repository content. Do not inspect personal data, credentials, messages, or document contents. Report concrete findings and focused test evidence; do not change files unless the audit identifies a real defect.'

fail() {
  local barrier=$1
  printf '%s\n' \
    "CHECK=FAIL barrier=$barrier" \
    'ISSUE_VALIDITY=VALID' \
    'LIFEOS_WORK_STATE=BLOCKED' \
    "BARRIER=$barrier" \
    'NEXT_AUTONOMOUS_ACTION=repair the named Pi5 diagnostic barrier and rerun the same launcher' \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    'RESULT=RETRY' \
    'TESTS=fresh Engineer privacy-path probe failed' \
    'NEXT_RUNTIME_CHECK=bash governor/runtime_jobs/37b55cb9080f.sh'
  exit 1
}

command -v python3 >/dev/null || fail python3_missing
command -v timeout >/dev/null || fail timeout_missing
[[ -r "$PLATFORM/governor/engineer_backend.py" ]] || fail engineer_backend_source_missing

set +e
output=$(timeout --signal=TERM --kill-after=5s 40s python3 - "$AGENT_URL" "$PLATFORM" "$REQUEST" <<'PY'
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime

agent_url, platform, request_text = sys.argv[1:]

def call(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        agent_url + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

def stop(code, detail):
    print(f"PROBE_STATE=FAIL code={code} detail={detail}")
    raise SystemExit(2)

health = call("/health")
if health.get("status") != "ok" or health.get("runtime_controller") != "pi5":
    stop("agent_health", "unexpected controller health")

matches = [j for j in call("/jobs").get("jobs", []) if j.get("request") == request_text]
if matches:
    summary = matches[0]
    job = call("/jobs/" + summary["id"])
    print(f"SUBMISSION=EXISTING job_id={job['id']}")
else:
    # Deliberately omit dispatch_builder: this tests the classifier itself rather
    # than the authenticated backlog runner's explicit routing assertion.
    job = call("/jobs?async=1", {"request": request_text})
    print(f"SUBMISSION=NEW job_id={job['id']}")

if job.get("privacy") != "normal":
    stop("privacy_classification", repr(job.get("privacy")))
if job.get("dispatch_builder") is not None:
    stop("classifier_bypassed", "dispatch_builder unexpectedly present")
print("PRIVACY_CLASSIFICATION=PASS value=normal source=automatic_classifier")

status = str(job.get("status", "UNKNOWN")).upper()
stage = str(job.get("stage", "unknown"))
if not job.get("created_at") or not job.get("stage_changed_at"):
    stop("status_telemetry", "timestamps absent")

spec = importlib.util.spec_from_file_location("lifeos_engineer_backend_probe", platform + "/governor/engineer_backend.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
report = backend.status_reply(job)
for marker in (f"**{status}**", f"**{stage}**", "Elapsed:"):
    if marker not in report:
        stop("status_reporting", "missing " + marker)
if status == "RUNNING" and not ("ETA estimate" in report or "defensible ETA" in report):
    stop("eta_reporting", "running report omitted ETA state")
print(f"REPORTING=PASS status={status} stage={stage} elapsed=present eta_state=correct")

if status in {"QUEUED", "RUNNING"}:
    print("PROBE_STATE=WAITING reason=fresh_job_must_run_after_parent_releases_execution_lock")
    raise SystemExit(3)
if status != "PASS":
    stop("fresh_job_terminal_status", status)

iterations = job.get("iterations") or []
if not iterations:
    stop("iteration_evidence", "missing")
last = iterations[-1]
evidence = str(last.get("evidence", ""))
verdict = last.get("verification") or {}
if "BUILDER_ROUTE=normal" not in evidence:
    stop("cloud_builder_route", "normal route absent")
if "cloud_builder_forbidden_for_local_only_job" in evidence:
    stop("cloud_builder_privacy_rejection", "forbidden marker present")
for section in ("PUBLICATION_EVIDENCE:", "PI5_RUNTIME_EVIDENCE:"):
    if section not in evidence:
        stop("pipeline_stage_evidence", section + " absent")
if verdict.get("verdict") != "PASS" or not str(verdict.get("reason", "")).strip():
    stop("local_verifier", "meaningful PASS verdict absent")
if not job.get("started_at") or not job.get("completed_at"):
    stop("elapsed_reporting", "terminal timestamps absent")
start = backend.parse_time(job["started_at"])
end = backend.parse_time(job["completed_at"])
if not start or not end or end < start:
    stop("elapsed_reporting", "timestamps invalid")
print("CLOUD_BUILDER_PATH=PASS route=normal privacy_rejection=absent")
print("PI5_PUBLICATION_RUNTIME=PASS evidence_sections=present")
print("LOCAL_VERIFIER=PASS verdict=meaningful")
print("PROBE_STATE=PASS")
PY
)
rc=$?
set -e
printf '%s\n' "$output"

case $rc in
  0)
    printf '%s\n' \
      'ISSUE_VALIDITY=VALID' \
      'LIFEOS_WORK_STATE=PASS' \
      'BARRIER=none' \
      'NEXT_AUTONOMOUS_ACTION=none; acceptance evidence is complete' \
      'DISCOVERED_ISSUES_JSON_B64=none' \
      'RESULT=PASS' \
      'TESTS=fresh ordinary Engineer audit passed classification, cloud builder, Pi5 runtime/publication, local verifier, and reporting checks' \
      'NEXT_RUNTIME_CHECK=none'
    ;;
  3)
    printf '%s\n' \
      'ISSUE_VALIDITY=VALID' \
      'LIFEOS_WORK_STATE=WAITING_DEPENDENCY' \
      'BARRIER=fresh job is queued behind the current job execution lock' \
      'NEXT_AUTONOMOUS_ACTION=rerun this idempotent launcher after the fresh Engineer job reaches a terminal state' \
      'DISCOVERED_ISSUES_JSON_B64=none' \
      'RESULT=RETRY' \
      'TESTS=fresh job submission and automatic normal classification passed; end-to-end terminal evidence pending' \
      'NEXT_RUNTIME_CHECK=bash governor/runtime_jobs/37b55cb9080f.sh'
    ;;
  *) fail "probe_python_rc_$rc" ;;
esac
