#!/usr/bin/env bash
set -Eeuo pipefail

readonly AGENT_URL=${LIFEOS_AGENT_URL:-http://127.0.0.1:8790}
readonly PLATFORM=${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}
readonly LIVE_AGENT=${LIFEOS_LIVE_AGENT:-/usr/local/libexec/lifeos-autonomous-agent}
readonly REQUEST='Issue 14 fresh privacy-classifier probe v2: Perform a read-only Engineer audit of repository code and documentation for consistency using only cloud-safe repository content. Report concrete findings and focused test evidence.'

emit_failure() {
  local barrier=$1
  printf '%s\n' \
    "CHECK=FAIL barrier=$barrier" \
    'ISSUE_VALIDITY=VALID' \
    'LIFEOS_WORK_STATE=BLOCKED' \
    "BARRIER=$barrier" \
    'NEXT_AUTONOMOUS_ACTION=repair the named Pi5 barrier and rerun this idempotent launcher' \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    'RESULT=RETRY' \
    'TESTS=fresh Engineer privacy-path probe failed' \
    'NEXT_RUNTIME_CHECK=bash governor/runtime_jobs/1fac7c6c2386.sh'
  exit 1
}

command -v python3 >/dev/null || emit_failure python3_missing
command -v timeout >/dev/null || emit_failure timeout_missing
[[ -r "$PLATFORM/governor/autonomous_agent.py" ]] || emit_failure source_agent_missing
[[ -r "$PLATFORM/governor/engineer_backend.py" ]] || emit_failure engineer_backend_source_missing
[[ -r "$LIVE_AGENT" ]] || emit_failure live_agent_missing

set +e
output=$(timeout --signal=TERM --kill-after=5s 50s python3 - "$AGENT_URL" "$PLATFORM" "$LIVE_AGENT" "$REQUEST" <<'PY'
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import urllib.request

agent_url, platform, live_agent, request_text = sys.argv[1:]

def stop(code, detail):
    print(f"PROBE_STATE=FAIL code={code} detail={detail}")
    raise SystemExit(2)

def call(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        agent_url + path, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

with tempfile.TemporaryDirectory(prefix="lifeos-privacy-probe-") as state:
    os.environ["LIFEOS_AGENT_STATE"] = state
    source_path = platform + "/governor/autonomous_agent.py"
    source = load_module("lifeos_source_agent_probe", source_path)
    live = load_module("lifeos_live_agent_probe", live_agent)
    if source.classify_privacy(request_text) != "normal":
        stop("source_ordinary_classification", "not normal")
    if live.classify_privacy(request_text) != "normal":
        stop("live_ordinary_classification", "not normal")
    controls = ("review my private documents", "inspect my bank statements")
    if any(source.classify_privacy(text) != "local-only" for text in controls):
        stop("source_sensitive_control", "not local-only")
    if any(live.classify_privacy(text) != "local-only" for text in controls):
        stop("live_sensitive_control", "not local-only")
    source_hash = hashlib.sha256(open(source_path, "rb").read()).hexdigest()
    live_hash = hashlib.sha256(open(live_agent, "rb").read()).hexdigest()
    if source_hash != live_hash:
        stop("source_live_hash_mismatch", f"source={source_hash} live={live_hash}")
print("CLASSIFIER_CONTROLS=PASS ordinary=normal sensitive=local-only source_live_hash=match")

health = call("/health")
if health.get("status") != "ok" or health.get("runtime_controller") != "pi5":
    stop("agent_health", "unexpected controller health")

matches = [job for job in call("/jobs").get("jobs", []) if job.get("request") == request_text]
if matches:
    job = call("/jobs/" + matches[0]["id"])
    print(f"SUBMISSION=EXISTING job_id={job['id']}")
else:
    job = call("/jobs?async=1", {"request": request_text})
    print(f"SUBMISSION=NEW job_id={job['id']}")

if job.get("privacy") != "normal":
    stop("fresh_job_privacy", repr(job.get("privacy")))
if job.get("dispatch_builder") is not None:
    stop("classifier_bypassed", "dispatch_builder unexpectedly present")

backend = load_module("lifeos_engineer_backend_probe", platform + "/governor/engineer_backend.py")
status = str(job.get("status", "UNKNOWN")).upper()
stage = str(job.get("stage", "unknown"))
report = backend.status_reply(job)
for marker in (f"**{status}**", f"**{stage}**", "Elapsed:"):
    if marker not in report:
        stop("status_reporting", "missing " + marker)
if status == "RUNNING" and not ("ETA estimate" in report or "defensible ETA" in report):
    stop("eta_reporting", "running report omitted ETA state")
if not job.get("created_at") or not job.get("stage_changed_at"):
    stop("status_telemetry", "timestamps absent")
print(f"REPORTING=PASS status={status} stage={stage} elapsed=present eta_state=correct")

if status in {"QUEUED", "RUNNING", "PENDING", "STAGING"}:
    print("PROBE_STATE=WAITING reason=fresh_job_not_terminal")
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
if verdict.get("verdict") not in {"PASS", "FAIL"} or not str(verdict.get("reason", "")).strip():
    stop("local_verifier", "meaningful verdict absent")
if not job.get("started_at") or not job.get("completed_at"):
    stop("elapsed_reporting", "terminal timestamps absent")
start = backend.parse_time(job["started_at"])
end = backend.parse_time(job["completed_at"])
if not start or not end or end < start:
    stop("elapsed_reporting", "timestamps invalid")
print("CLOUD_BUILDER_PATH=PASS route=normal privacy_rejection=absent")
print("PI5_PUBLICATION_RUNTIME=PASS evidence_sections=present")
print(f"LOCAL_VERIFIER=PASS verdict={verdict['verdict']} reason=present")
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
      'NEXT_AUTONOMOUS_ACTION=none; end-to-end acceptance evidence is complete' \
      'DISCOVERED_ISSUES_JSON_B64=none' \
      'RESULT=PASS' \
      'TESTS=fresh ordinary Engineer audit passed classifier controls, cloud builder, Pi5 publication/runtime, local verifier, and reporting checks' \
      'NEXT_RUNTIME_CHECK=none'
    ;;
  3)
    printf '%s\n' \
      'ISSUE_VALIDITY=VALID' \
      'LIFEOS_WORK_STATE=WAITING_DEPENDENCY' \
      'BARRIER=fresh job has not reached a terminal state' \
      'NEXT_AUTONOMOUS_ACTION=rerun this idempotent launcher after the fresh Engineer job advances' \
      'DISCOVERED_ISSUES_JSON_B64=none' \
      'RESULT=RETRY' \
      'TESTS=source/live classifier controls and fresh normal classification passed; terminal pipeline evidence pending' \
      'NEXT_RUNTIME_CHECK=bash governor/runtime_jobs/1fac7c6c2386.sh'
    ;;
  *) emit_failure "probe_python_rc_$rc" ;;
esac
