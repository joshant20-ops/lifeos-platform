#!/usr/bin/env python3
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import pathlib
import re
import socket
import statistics
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_JOB_RECORDS_SPEC = importlib.util.spec_from_file_location(
    "lifeos_job_records", pathlib.Path(__file__).with_name("job_records.py")
)
_JOB_RECORDS = importlib.util.module_from_spec(_JOB_RECORDS_SPEC)
_JOB_RECORDS_SPEC.loader.exec_module(_JOB_RECORDS)
publish_record = _JOB_RECORDS.publish_record

ROOT = pathlib.Path(os.environ.get("LIFEOS_AGENT_STATE", "/var/lib/lifeos-agent"))
ROOT.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("LIFEOS_AGENT_PORT", "8790"))
MAX_ITERATIONS = int(os.environ.get("LIFEOS_AGENT_MAX_ITERATIONS", "8"))
BUILDER = os.environ.get("LIFEOS_AGENT_BUILDER", "/usr/local/libexec/lifeos-cloud-builder")
LOCAL_BUILDER = os.environ.get("LIFEOS_AGENT_LOCAL_BUILDER", "")
DISPATCH_TOKEN_FILE = os.environ.get("LIFEOS_BACKLOG_DISPATCH_TOKEN_FILE", "")
VERIFIER_URL = os.environ.get("LIFEOS_LOCAL_VERIFIER_URL", "http://192.168.0.201:11434/api/generate")
VERIFIER_MODEL = os.environ.get("LIFEOS_LOCAL_VERIFIER_MODEL", "qwen2.5-coder:7b-instruct")
PLATFORM_REPO = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform")).resolve()
UI_PATH = PLATFORM_REPO / "governor" / "agent_ui.html"
RUNTIME_PREFIX = "governor/runtime_jobs/"
JOB_ID_PATTERN = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
MAX_PATCH_BYTES = 1048576
MAX_RUNTIME_BYTES = 65536
REPEATED_FAILURE_LIMIT = int(os.environ.get("LIFEOS_REPEATED_FAILURE_LIMIT", "3"))
STUCK_JOB_MULTIPLIER = float(os.environ.get("LIFEOS_STUCK_JOB_MULTIPLIER", "3.0"))
STUCK_JOB_MIN_SECONDS = int(os.environ.get("LIFEOS_STUCK_JOB_MIN_SECONDS", "300"))
CONTINUATION_MAX_DEPTH = int(os.environ.get("LIFEOS_CONTINUATION_MAX_DEPTH", "4"))
EXECUTION_LOCK = threading.Lock()
DISPATCH_BUILDER_CLASSES = frozenset({"normal", "local"})

INCOMPLETE_CONTRACT_STATES = frozenset({
    "PENDING", "NOT_STARTED", "NOT_IMPLEMENTED", "NOT_VERIFIED",
    "NOT_ATTEMPTED", "UNKNOWN", "INCOMPLETE",
})


def submit_control_job(manifest_json, script_bytes):
    """Submit only an exact manifest and script to the local fixed-purpose bridge."""
    if not isinstance(manifest_json, str) or not isinstance(script_bytes, (bytes, bytearray)):
        return {"status": "REJECTED", "reason": "manifest_json and script bytes required"}
    if len(manifest_json.encode()) > 32768 or len(script_bytes) > 262144:
        return {"status": "REJECTED", "reason": "control-job package exceeds size limit"}
    request = {
        "operation": "submit-control-job",
        "manifest": manifest_json,
        "script_base64": base64.b64encode(bytes(script_bytes)).decode("ascii"),
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(15)
            client.connect("/run/lifeos-control-job-submit.sock")
            client.sendall(json.dumps(request, separators=(",", ":")).encode())
            client.shutdown(socket.SHUT_WR)
            response = b""
            while len(response) <= 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
        result = json.loads(response)
        return result if isinstance(result, dict) else {"status": "REJECTED", "reason": "invalid bridge response"}
    except Exception as exc:
        return {"status": "REJECTED", "reason": f"submission bridge unavailable: {type(exc).__name__}"}


def request_engineer_runtime_deployment(job_id):
    """Request one fixed broker operation; no command, path, unit, or argument is delegated."""
    request = {"operation": "deploy-engineer-runtime", "job_id": str(job_id), "target": "pi5"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(180)
            client.connect("/run/lifeos-root-broker.sock")
            client.sendall((json.dumps(request, sort_keys=True) + "\n").encode())
            client.shutdown(socket.SHUT_WR)
            response = b""
            while len(response) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
        payload = json.loads(response.decode())
        if not isinstance(payload, dict):
            raise ValueError("broker response was not an object")
        return payload
    except Exception as exc:
        return {"status": "REJECTED", "reason": f"root broker unavailable: {type(exc).__name__}"}

PRIVATE_PATTERNS = (
    r"\bpaperless\b",
    r"\bprivate (?:data|documents?|files?|records?|information)\b",
    r"\bpersonal (?:data|documents?|files?|records?|information)\b",
    r"\bmedical (?:data|records?|documents?|information)\b",
    r"\bhealth (?:data|records?|documents?|information)\b",
    r"\bpassport(?:s)?\b",
    r"\bbank (?:accounts?|statements?|details|records?|documents?)\b",
    r"\bfinancial (?:statements?|records?|data|documents?)\b",
    r"\bpersonal (?:invoice|invoices|email|emails|mailbox|inbox)\b",
    r"\b(?:email|emails|mailbox|inbox)\b.{0,40}\b(?:private|personal|messages?|content)\b",
)

PROTECTED_CONTINUATION_TERMS = (
    "root broker", "allow-list", "allowlist", "job publisher", "job runner",
    "checksum enforcement", "secret boundary", "protected deployment authority",
)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None


def job_path(job_id):
    return ROOT / f"{job_id}.json"


def save(job):
    tmp = job_path(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2, sort_keys=True))
    os.replace(tmp, job_path(job["id"]))


def load(job_id):
    return json.loads(job_path(job_id).read_text())


def list_jobs(limit=None):
    jobs = []
    paths = sorted(ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        paths = paths[:limit]
    for path in paths:
        try:
            jobs.append(json.loads(path.read_text()))
        except Exception:
            continue
    return jobs


def set_stage(job, stage, detail=None):
    job["stage"] = stage
    job["stage_changed_at"] = now()
    if detail:
        job["stage_detail"] = str(detail)[:1000]
    else:
        job.pop("stage_detail", None)
    save(job)


def finish_job(job, stage, detail=None):
    """Persist terminal runtime state and attempt its sanitised Git record."""
    set_stage(job, stage, detail)
    job["record_publication"] = publish_record(PLATFORM_REPO, job)
    save(job)
    return job


def completed_job_durations(jobs=None):
    durations = []
    for job in jobs if jobs is not None else list_jobs():
        if str(job.get("status") or "").upper() != "PASS":
            continue
        start = _parse_time(job.get("started_at") or job.get("created_at"))
        end = _parse_time(job.get("completed_at"))
        if start and end and end >= start:
            durations.append((end - start).total_seconds())
    return durations


def stuck_jobs(jobs=None, at=None):
    jobs = list(jobs if jobs is not None else list_jobs())
    at = at or datetime.now().astimezone()
    history = completed_job_durations(jobs)
    historical_limit = 0.0
    if history:
        historical_limit = max(
            statistics.median(history) * STUCK_JOB_MULTIPLIER,
            max(history) * 1.5,
        )
    threshold = max(float(STUCK_JOB_MIN_SECONDS), historical_limit)
    result = []
    for job in jobs:
        status = str(job.get("status") or "").upper()
        if status not in ("RUNNING", "QUEUED", "PENDING", "STAGING"):
            continue
        changed = _parse_time(job.get("stage_changed_at") or job.get("started_at") or job.get("created_at"))
        if not changed:
            continue
        age = max(0.0, (at - changed).total_seconds())
        if age <= threshold:
            continue
        item = {k: job.get(k) for k in (
            "id", "status", "stage", "stage_changed_at", "created_at", "started_at",
            "request", "repeated_failure_count",
        ) if k in job}
        item["stage_age_seconds"] = int(age)
        item["stuck_threshold_seconds"] = int(threshold)
        source = "persisted successful-job duration history" if historical_limit else "minimum deterministic threshold"
        item["stuck_reason"] = (
            f"stage has not advanced for {int(age)}s, exceeding conservative threshold "
            f"{int(threshold)}s from {source}"
        )
        result.append(item)
    return result


def classify_privacy(text):
    lower = str(text or "").lower()
    return "local-only" if any(re.search(pattern, lower) for pattern in PRIVATE_PATTERNS) else "normal"


def _dispatcher_token():
    path = DISPATCH_TOKEN_FILE
    if not path:
        credentials = os.environ.get("CREDENTIALS_DIRECTORY", "")
        if credentials:
            path = str(pathlib.Path(credentials) / "backlog-dispatcher.token")
    if not path:
        return ""
    try:
        return pathlib.Path(path).read_text().strip()
    except OSError:
        return ""


def authenticated_dispatch_route(headers, body):
    """Validate the backlog dispatcher's bounded, authenticated route assertion."""
    if "dispatch_builder" not in body:
        return None, None
    route = body.get("dispatch_builder")
    if not isinstance(route, str) or route not in DISPATCH_BUILDER_CLASSES:
        return None, "invalid_dispatch_builder"
    expected = _dispatcher_token()
    supplied = str(headers.get("Authorization", ""))
    if not expected or not supplied.startswith("Bearer "):
        return None, "dispatcher_capability_required"
    if not hmac.compare_digest(supplied[7:].encode(), expected.encode()):
        return None, "dispatcher_capability_required"
    return route, None


def extract_mandatory_final_fields(request):
    """Return reusable KEY= final-contract fields explicitly declared by a job."""
    fields = []
    in_contract = False
    for raw_line in str(request or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if ("final status must explicitly report" in lowered
                or "final output contract" in lowered):
            in_contract = True
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*=.*", line)
        if in_contract and match and match.group(1) not in fields:
            fields.append(match.group(1))
    return fields


def _contract_value(evidence, field):
    values = re.findall(rf"(?m)^{re.escape(field)}\s*=\s*(.*?)\s*$", str(evidence or ""))
    return values[-1] if values else None


def milestone_decision(job, iteration_verdict, evidence):
    """Separate an independent iteration verdict from milestone completion."""
    verdict = str((iteration_verdict or {}).get("verdict") or "RETRY").upper()
    if verdict not in {"PASS", "RETRY", "BLOCKED"}:
        verdict = "RETRY"
    result = {
        "iteration_result": verdict,
        "milestone_result": verdict,
        "reason": str((iteration_verdict or {}).get("reason") or ""),
        "next_instruction": str((iteration_verdict or {}).get("next_instruction") or ""),
    }
    # BLOCKED remains an independent verifier decision for an external dependency.
    if verdict != "PASS":
        return result
    fields = list(job.get("mandatory_final_fields") or [])
    incomplete = []
    for field in fields:
        value = _contract_value(evidence, field)
        normalized = re.sub(r"[\s-]+", "_", str(value or "").strip().upper())
        if value is None or normalized in INCOMPLETE_CONTRACT_STATES:
            incomplete.append(field)
    if incomplete:
        result["milestone_result"] = "RETRY"
        result["reason"] = "mandatory milestone contract is incomplete: " + ", ".join(incomplete)
        result["next_instruction"] = (
            "Continue with the next useful phase and provide completed evidence for: "
            + ", ".join(incomplete)
        )
    return result


def local_verify(job, iteration, evidence):
    prompt = f"""You are the independent LOCAL verifier for LifeOS.
Decide whether the user's original goal is actually complete from supplied BUILD, PUBLICATION, AND RUNTIME evidence.
Return JSON only with keys: verdict, reason, next_instruction.
verdict must be PASS, RETRY, or BLOCKED.

Rules:
- PASS only when evidence demonstrates the requested outcome works.
- RETRY when there is any actionable engineering, deployment, configuration, testing, or repair step the autonomous system can attempt itself.
- BLOCKED is reserved for a genuinely external blocker the autonomous system cannot resolve itself, such as missing user-only credentials, unavailable required hardware, a required physical action, or a safety/privacy policy prohibition.
- Unrelated pre-existing repository failures are not a blocker for a scoped job.
- A builder saying BLOCKED does not force BLOCKED if the issue is internally actionable.
- Do not ask the user to run diagnostics the automation can run itself.
- Do not assume success merely because a process exited zero.
- If evidence shows the same deterministic failure as a prior iteration, change the plan materially rather than repeating the same action.

User goal: {job['request']}
Privacy class: {job['privacy']}
Iteration: {iteration}
Evidence:\n{evidence[-18000:]}
"""
    payload = json.dumps({
        "model": VERIFIER_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_ctx": 8192},
    }).encode()
    req = urllib.request.Request(VERIFIER_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as response:
        result = json.load(response)
    raw = result.get("response", "{}")
    try:
        return json.loads(raw)
    except Exception:
        return {"verdict": "RETRY", "reason": "verifier returned invalid JSON", "next_instruction": "Repeat focused local verification and return valid JSON."}


def _marker(text, name):
    m = re.findall(rf"(?m)^{re.escape(name)}=(.*)$", text)
    return m[-1].strip() if m else None


def parse_handoff(raw):
    handoff = {
        "base": _marker(raw, "HANDOFF_BASE"),
        "patch_b64": _marker(raw, "HANDOFF_PATCH_B64"),
        "runtime_b64": _marker(raw, "HANDOFF_RUNTIME_B64"),
        "run_script": _marker(raw, "RUN_SCRIPT"),
    }
    sanitized = re.sub(r"(?m)^HANDOFF_(?:PATCH|RUNTIME)_B64=.*$", "HANDOFF_PAYLOAD=[redacted from verifier evidence]", raw)
    return handoff, sanitized


def failure_signature(evidence, verdict):
    lines = []
    patterns = (
        r"(?m)^RUNTIME_RC=.*$",
        r"(?m)^RESULT=FAIL.*$",
        r"(?m)^REASON=.*$",
        r"(?m)^DEPLOYMENT_FAILURE=.*$",
        r"(?m)^PRIVILEGED_BOOTSTRAP_REQUIRED.*$",
        r"(?m)^PI5_PATCH=RETRY.*$",
        r"(?m)^HANDOFF_ERROR=.*$",
    )
    for pattern in patterns:
        matches = re.findall(pattern, evidence)
        if matches:
            lines.append(matches[-1])
    reason = str((verdict or {}).get("reason") or "").strip()
    if reason:
        lines.append("VERIFIER_REASON=" + reason[:1000])
    if not lines:
        return None
    normalized = "\n".join(lines)
    normalized = re.sub(r"\b[a-f0-9]{12,64}\b", "<id>", normalized, flags=re.I)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}T[^\s]+", "<time>", normalized)
    normalized = re.sub(r"line=\d+", "line=<n>", normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def update_failure_history(job, signature):
    if not signature:
        job["repeated_failure_count"] = 0
        job.pop("last_failure_signature", None)
        return 0
    if job.get("last_failure_signature") == signature:
        count = int(job.get("repeated_failure_count") or 1) + 1
    else:
        count = 1
    job["last_failure_signature"] = signature
    job["repeated_failure_count"] = count
    return count


def run_builder(job, iteration, verifier_feedback=None):
    route, builder = builder_route(job)
    if not builder:
        return 78, "BUILDER_ROUTE=local\nLOCAL_BUILDER=UNAVAILABLE\n", {
            "_builder_route": route,
        }
    env = os.environ.copy()
    env["LIFEOS_JOB_ID"] = job["id"]
    env["LIFEOS_JOB_PRIVACY"] = job["privacy"]
    args = [builder, job["request"], str(iteration)]
    if verifier_feedback:
        args.append(verifier_feedback)
    cp = subprocess.run(args, text=True, capture_output=True, timeout=1800, env=env)
    raw = (cp.stdout or "") + "\n" + (cp.stderr or "")
    handoff, evidence = parse_handoff(raw)
    handoff["_builder_route"] = route
    return cp.returncode, f"BUILDER_ROUTE={route}\n" + evidence, handoff


def builder_route(job):
    """Select a capable builder without weakening the job's privacy class."""
    route = job.get("dispatch_builder")
    if route is None:
        route = "local" if job.get("privacy") == "local-only" else "normal"
    if route == "normal":
        return "normal", BUILDER
    if LOCAL_BUILDER and pathlib.Path(LOCAL_BUILDER).is_file() and os.access(LOCAL_BUILDER, os.X_OK):
        return "local", LOCAL_BUILDER
    return "local", None


def git(*args, check=True, timeout=120):
    return subprocess.run(["git", *args], cwd=PLATFORM_REPO, text=True, capture_output=True, check=check, timeout=timeout)


def repo_context():
    result = {"status": "ok"}
    try:
        result["head"] = git("rev-parse", "HEAD").stdout.strip()
        result["branch"] = git("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip() or "detached"
        result["dirty"] = bool(git("status", "--porcelain", check=False).stdout.strip())
        result["origin_main"] = git("rev-parse", "origin/main", check=False).stdout.strip()
    except Exception as exc:
        return {"status": "unavailable", "detail": type(exc).__name__}
    running = [j for j in list_jobs(20) if j.get("status") in ("QUEUED", "RUNNING")]
    result["active_jobs"] = [
        {k: j.get(k) for k in ("id", "status", "stage", "stage_changed_at", "created_at", "started_at", "request")}
        for j in running[:5]
    ]
    result["stuck_jobs"] = stuck_jobs(list_jobs(100))
    return result


def apply_and_publish_patch(job, iteration, handoff):
    payload = handoff.get("patch_b64")
    if not payload:
        return "PI5_PATCH=none\n"
    if job["privacy"] == "local-only" and handoff.get("_builder_route") != "local":
        return "PI5_PATCH=blocked_for_cloud_authored_private_job\n"
    try:
        patch = base64.b64decode(payload, validate=True)
    except Exception as exc:
        return f"PI5_PATCH=invalid_base64 error={type(exc).__name__}\n"
    if len(patch) > MAX_PATCH_BYTES:
        return f"PI5_PATCH=rejected size={len(patch)} limit={MAX_PATCH_BYTES}\n"
    status = git("status", "--porcelain").stdout.strip()
    if status:
        return "PI5_PATCH=retry canonical_checkout_dirty\n" + status[-4000:] + "\n"
    try:
        git("fetch", "origin", "main")
        head = git("rev-parse", "HEAD").stdout.strip()
        origin_main = git("rev-parse", "origin/main").stdout.strip()
        if head != origin_main:
            return f"PI5_PATCH=retry canonical_not_at_origin_main head={head} origin_main={origin_main}\n"
        patch_file = ROOT / f"{job['id']}-{iteration}.patch"
        patch_file.write_bytes(patch)
        subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=PLATFORM_REPO, check=True, text=True, capture_output=True, timeout=30)
        subprocess.run(["git", "apply", str(patch_file)], cwd=PLATFORM_REPO, check=True, text=True, capture_output=True, timeout=30)
        patch_file.unlink(missing_ok=True)
        git("add", "-A")
        git("diff", "--cached", "--check")
        staged = git("diff", "--cached", "--name-only").stdout.splitlines()
        if not staged:
            return "PI5_PATCH=no_effect\n"
        commit = git("commit", "-m", f"agent: job {job['id']} iteration {iteration}", timeout=60).stdout
        sha = git("rev-parse", "HEAD").stdout.strip()
        push = git("push", "origin", "HEAD:main", timeout=180)
        return "PI5_PATCH=APPLIED\nPI5_COMMIT=" + sha + "\nPI5_FILES=" + ",".join(staged[:50]) + "\nPI5_PUSH=PASS\n" + commit[-2000:] + push.stdout[-1000:] + push.stderr[-1000:] + "\n"
    except subprocess.CalledProcessError as exc:
        detail = ((exc.stdout or "") + "\n" + (exc.stderr or ""))[-5000:]
        return f"PI5_PATCH=RETRY error=command_failed rc={exc.returncode}\n{detail}\n"
    except Exception as exc:
        return f"PI5_PATCH=RETRY error={type(exc).__name__}:{exc}\n"


def _runtime_candidate_path(job_id):
    candidate_dir = ROOT / "artifact_candidates"
    candidate_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    return candidate_dir / f"{job_id}.sh"


def _artifact_evidence(rel, digest, commit, published, reason=None):
    lines = [
        f"RUNTIME_ARTIFACT_PATH={rel}",
        f"RUNTIME_ARTIFACT_SHA256={digest or 'UNAVAILABLE'}",
        f"RUNTIME_ARTIFACT_COMMIT={commit or 'UNAVAILABLE'}",
        f"RUNTIME_ARTIFACT_PUBLISHED={'PASS' if published else 'FAIL'}",
    ]
    if reason:
        lines.extend((f"RUNTIME_ARTIFACT_REASON={reason}", "HUMAN_ACTION_REQUIRED_ARTIFACT_NOT_PUBLISHED"))
    return "\n".join(lines) + "\n"


def suppress_unpublished_runtime_instructions(evidence):
    """Remove executable human instructions when their artifact was not published."""
    filtered = []
    for line in evidence.splitlines():
        if line.startswith(("HUMAN_ACTION_REQUIRED=", "NEXT_RUNTIME_CHECK=")):
            filtered.append("HUMAN_ACTION_REQUIRED_ARTIFACT_NOT_PUBLISHED")
            continue
        # Builder prose is untrusted evidence too. Never retain a copy/paste sudo
        # command for a runtime_jobs artifact whose publication did not verify.
        line = re.sub(
            r"sudo\s+\S*governor/runtime_jobs/[A-Za-z0-9._/-]+\.sh",
            "[unpublished runtime command suppressed]",
            line,
        )
        filtered.append(line)
    return "\n".join(filtered) + ("\n" if evidence.endswith("\n") else "")


def verify_runtime_artifact(job_id):
    """Prove canonical, executable, tracked bytes are exactly on origin/main."""
    if not JOB_ID_PATTERN.fullmatch(str(job_id)):
        return False, _artifact_evidence(
            f"{RUNTIME_PREFIX}[rejected].sh", None, None, False, "invalid_job_id"
        )
    rel = f"{RUNTIME_PREFIX}{job_id}.sh"
    target = PLATFORM_REPO / rel
    try:
        target.relative_to(PLATFORM_REPO)
        if target.is_symlink() or not target.is_file():
            return False, _artifact_evidence(rel, None, None, False, "canonical_file_missing_or_unsafe")
        if not os.access(target, os.X_OK):
            return False, _artifact_evidence(rel, None, None, False, "canonical_file_not_executable")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        tracked = git("ls-files", "--error-unmatch", "--", rel, check=False)
        if tracked.returncode:
            return False, _artifact_evidence(rel, digest, None, False, "canonical_file_untracked")
        commit = git("log", "-1", "--format=%H", "--", rel, check=False).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            return False, _artifact_evidence(rel, digest, None, False, "canonical_commit_missing")
        blob = git("show", f"{commit}:{rel}", check=False)
        if blob.returncode or hashlib.sha256(blob.stdout.encode()).hexdigest() != digest:
            return False, _artifact_evidence(rel, digest, commit, False, "canonical_commit_blob_mismatch")
        origin = git("merge-base", "--is-ancestor", commit, "origin/main", check=False)
        origin_blob = git("show", f"origin/main:{rel}", check=False)
        if origin.returncode or origin_blob.returncode or hashlib.sha256(origin_blob.stdout.encode()).hexdigest() != digest:
            return False, _artifact_evidence(rel, digest, commit, False, "origin_main_mismatch")
        return True, _artifact_evidence(rel, digest, commit, True)
    except Exception as exc:
        return False, _artifact_evidence(rel, None, None, False, f"verification_error_{type(exc).__name__}")


def publish_runtime_artifact(job, handoff):
    """Persist a candidate, then publish and prove it before it may be referenced."""
    if not JOB_ID_PATTERN.fullmatch(str(job.get("id", ""))):
        return False, _artifact_evidence(
            f"{RUNTIME_PREFIX}[rejected].sh", None, None, False, "invalid_job_id"
        )
    rel = handoff.get("run_script")
    payload = handoff.get("runtime_b64")
    expected = f"{RUNTIME_PREFIX}{job['id']}.sh"
    if not rel and not payload:
        return False, "RUNTIME_ACTION=none_declared\n"
    if rel != expected:
        return False, _artifact_evidence(expected, None, None, False, "rejected_path")
    if job["privacy"] == "local-only" and handoff.get("_builder_route") != "local":
        return False, _artifact_evidence(expected, None, None, False, "cloud_authored_private_job")
    try:
        script = base64.b64decode(payload or "", validate=True)
        if len(script) > MAX_RUNTIME_BYTES:
            raise ValueError("size_limit")
        text = script.decode("utf-8", errors="strict")
        if not text.startswith("#!/usr/bin/env bash"):
            raise ValueError("invalid_shebang")
    except Exception as exc:
        return False, _artifact_evidence(expected, None, None, False, f"invalid_payload_{type(exc).__name__}")
    candidate = _runtime_candidate_path(job["id"])
    candidate.write_bytes(script)
    candidate.chmod(0o700)
    digest = hashlib.sha256(script).hexdigest()
    already, evidence = verify_runtime_artifact(job["id"])
    if already:
        return True, evidence
    if git("status", "--porcelain", check=False).stdout.strip():
        return False, _artifact_evidence(expected, digest, None, False, "canonical_checkout_dirty")
    target = PLATFORM_REPO / expected
    try:
        if target.is_symlink():
            return False, _artifact_evidence(expected, digest, None, False, "symlink_rejected")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{job['id']}.tmp")
        temporary.write_bytes(script)
        temporary.chmod(0o755)
        os.replace(temporary, target)
        git("add", "--", expected)
        git("diff", "--cached", "--check")
        if git("diff", "--cached", "--quiet", check=False).returncode:
            git("commit", "-m", f"agent: publish runtime artifact {job['id']}", timeout=60)
        git("push", "origin", "HEAD:main", timeout=180)
        return verify_runtime_artifact(job["id"])
    except Exception as exc:
        return False, _artifact_evidence(expected, digest, None, False, f"publication_error_{type(exc).__name__}")


def run_pi5_runtime(job, handoff):
    rel = handoff.get("run_script")
    payload = handoff.get("runtime_b64")
    if not rel and not payload:
        return "RUNTIME_ACTION=none_declared\n"
    published, publication = publish_runtime_artifact(job, handoff)
    if not published:
        return publication
    target = PLATFORM_REPO / rel
    cp = subprocess.run(
        ["/usr/bin/timeout", "900s", str(target)],
        cwd=PLATFORM_REPO,
        text=True,
        capture_output=True,
        timeout=930,
        env={**os.environ, "LIFEOS_JOB_ID": job["id"], "LIFEOS_JOB_REQUEST": job["request"]},
    )
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    return publication + f"RUNTIME_SCRIPT={rel}\nRUNTIME_RC={cp.returncode}\nPI5_RUNTIME_EVIDENCE:\n{out[-16000:]}\n"


def _execute_job_locked(job):
    job = load(job["id"])
    job["status"] = "RUNNING"
    job["started_at"] = now()
    set_stage(job, "starting")
    feedback = None
    for iteration in range(1, MAX_ITERATIONS + 1):
        rec = {"iteration": iteration, "started_at": now()}
        set_stage(job, "builder", f"iteration {iteration}: Codex implementation")
        try:
            rc, build_evidence, handoff = run_builder(job, iteration, feedback)
            rec["builder_rc"] = rc
        except Exception as exc:
            build_evidence = f"builder exception: {type(exc).__name__}: {exc}"
            handoff = {}
            rec["builder_rc"] = 255

        set_stage(job, "publication", f"iteration {iteration}: apply/publish patch")
        publication = apply_and_publish_patch(job, iteration, handoff)
        set_stage(job, "runtime", f"iteration {iteration}: Pi5 runtime verification")
        runtime = run_pi5_runtime(job, handoff)
        if "RUNTIME_ARTIFACT_PUBLISHED=FAIL" in runtime:
            build_evidence = suppress_unpublished_runtime_instructions(build_evidence)
        evidence = f"BUILD_EVIDENCE:\n{build_evidence[-12000:]}\n\nPUBLICATION_EVIDENCE:\n{publication[-7000:]}\n\n{runtime}"
        rec["evidence"] = evidence[-26000:]

        set_stage(job, "verifier", f"iteration {iteration}: local Qwen verification")
        try:
            verdict = local_verify(job, iteration, rec["evidence"])
        except Exception as exc:
            verdict = {"verdict": "RETRY", "reason": f"local verifier unavailable: {type(exc).__name__}", "next_instruction": "Retry local verifier and runtime verification."}
        rec["verification"] = verdict
        decision = milestone_decision(job, verdict, rec["evidence"])
        rec["iteration_result"] = decision["iteration_result"]
        rec["milestone_result"] = decision["milestone_result"]
        rec["finished_at"] = now()
        signature = failure_signature(rec["evidence"], verdict)
        if signature:
            rec["failure_signature"] = signature
        job.setdefault("iterations", []).append(rec)
        v = decision["milestone_result"]

        if v == "PASS":
            if bool(job.get("deploy_engineer_runtime")):
                set_stage(job, "deployment", "requesting approved bounded Engineer runtime deployment")
                job["deployment"] = request_engineer_runtime_deployment(job["id"])
                if job["deployment"].get("status") != "PASS":
                    job["status"] = "BLOCKED"
                    job["blocked_reason"] = "bounded runtime deployment was not approved or failed"
                    job["completed_at"] = now()
                    return finish_job(job, "blocked", job["blocked_reason"])
            job["status"] = "PASS"
            job["completed_at"] = now()
            return finish_job(job, "complete", "local verifier accepted result")
        if v == "BLOCKED":
            job["status"] = "BLOCKED"
            job["blocked_reason"] = decision.get("reason")
            job["completed_at"] = now()
            return finish_job(job, "blocked", job["blocked_reason"])

        repeat_count = update_failure_history(job, signature)
        if repeat_count >= REPEATED_FAILURE_LIMIT:
            job["status"] = "BLOCKED"
            job["blocked_reason"] = (
                f"repeated deterministic failure detected ({repeat_count} occurrences); "
                "stopped before exhausting the full iteration budget"
            )
            job["completed_at"] = now()
            return finish_job(job, "blocked_repeated_failure", job["blocked_reason"])

        base_feedback = str(decision.get("next_instruction") or decision.get("reason") or "Verification failed; continue toward the original goal using the evidence.")
        if repeat_count >= 2:
            feedback = (
                f"REPLAN REQUIRED: failure signature {signature} repeated {repeat_count} times. "
                "Do not repeat the previous implementation/runtime approach. Diagnose the deterministic cause and choose a materially different plan. "
                + base_feedback
            )
        else:
            feedback = base_feedback
        set_stage(job, "retry_planning", f"iteration {iteration} failed; preparing next plan")
        save(job)

    job["status"] = "BLOCKED"
    job["blocked_reason"] = "maximum iterations reached"
    job["completed_at"] = now()
    return finish_job(job, "blocked", job["blocked_reason"])


def continuation_allowed(job):
    if not bool(job.get("continuation_enabled")):
        return False
    if str(job.get("status") or "").upper() != "PASS":
        return False
    if int(job.get("continuation_depth") or 0) >= CONTINUATION_MAX_DEPTH:
        return False
    request = str(job.get("continuation_request") or "").strip()
    if not request:
        return False
    if any(term in request.lower() for term in PROTECTED_CONTINUATION_TERMS):
        return False
    # BLOCKED and repeated deterministic failure stop before this point.
    return True


def spawn_continuation(job):
    if not continuation_allowed(job):
        return None
    child = new_job(
        str(job["continuation_request"]),
        continuation_enabled=True,
        continuation_parent=job["id"],
        continuation_depth=int(job.get("continuation_depth") or 0) + 1,
        continuation_reason=str(job.get("continuation_reason") or "explicit bounded continuation"),
    )
    parent = load(job["id"])
    parent["continuation_child"] = child["id"]
    save(parent)
    threading.Thread(target=execute_job, args=(child,), daemon=True, name=f"job-{child['id']}").start()
    return child


def execute_job(job):
    with EXECUTION_LOCK:
        final = _execute_job_locked(job)
    spawn_continuation(final)


def new_job(request, retry_of=None, continuation_enabled=False, continuation_parent=None,
            continuation_depth=0, continuation_reason=None, continuation_request=None,
            deploy_engineer_runtime=False, dispatch_builder=None):
    privacy = (
        "local-only" if dispatch_builder == "local"
        else "normal" if dispatch_builder == "normal"
        else classify_privacy(request)
    )
    job = {
        "id": uuid.uuid4().hex[:12],
        "created_at": now(),
        "request": request.strip(),
        "privacy": privacy,
        "status": "QUEUED",
        "stage": "queued",
        "stage_changed_at": now(),
        "iterations": [],
        "repeated_failure_count": 0,
        "continuation_enabled": bool(continuation_enabled),
        "continuation_depth": int(continuation_depth or 0),
        "deploy_engineer_runtime": bool(deploy_engineer_runtime),
        "mandatory_final_fields": extract_mandatory_final_fields(request),
    }
    if retry_of:
        job["retry_of"] = retry_of
    if dispatch_builder in DISPATCH_BUILDER_CLASSES:
        job["dispatch_builder"] = dispatch_builder
    if continuation_parent:
        job["continuation_parent"] = continuation_parent
    if continuation_reason:
        job["continuation_reason"] = str(continuation_reason)[:1000]
    if continuation_request:
        job["continuation_request"] = str(continuation_request).strip()
    save(job)
    return job


def create_job(request, async_mode=False, retry_of=None, **continuation):
    job = new_job(request, retry_of=retry_of, **continuation)
    if async_mode:
        threading.Thread(target=execute_job, args=(job,), daemon=True, name=f"job-{job['id']}").start()
        return job
    execute_job(job)
    return load(job["id"])


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, payload):
        self.send_bytes(code, json.dumps(payload, sort_keys=True).encode(), "application/json")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/ui"):
            try:
                self.send_bytes(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
            except Exception as exc:
                self.send_json(503, {"error": "ui_unavailable", "detail": type(exc).__name__})
            return
        if path == "/health":
            self.send_json(200, {
                "service": "lifeos-autonomous-agent",
                "status": "ok",
                "max_iterations": MAX_ITERATIONS,
                "repeated_failure_limit": REPEATED_FAILURE_LIMIT,
                "stuck_job_multiplier": STUCK_JOB_MULTIPLIER,
                "max_continuation_depth": CONTINUATION_MAX_DEPTH,
                "continuation_max_depth": CONTINUATION_MAX_DEPTH,
                "runtime_controller": "pi5",
                "git_controller": "pi5",
                "ui": "/",
            })
            return
        if path == "/context":
            self.send_json(200, repo_context())
            return
        if path == "/jobs":
            jobs = list_jobs()
            keys = (
                "id", "created_at", "started_at", "completed_at", "request", "privacy", "status",
                "stage", "stage_changed_at", "stage_detail", "retry_of", "repeated_failure_count",
                "continuation_enabled", "continuation_parent", "continuation_child",
                "continuation_depth", "continuation_reason",
                "dispatch_builder",
            )
            self.send_json(200, {"jobs": [{k: j.get(k) for k in keys if k in j} for j in jobs]})
            return
        if path == "/jobs/stuck":
            self.send_json(200, {"stuck_jobs": stuck_jobs()})
            return
        if path.startswith("/jobs/"):
            job_id = path.split("/", 2)[2]
            try:
                self.send_json(200, load(job_id))
            except Exception:
                self.send_json(404, {"error": "not_found"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/jobs/") and path.endswith("/retry"):
            job_id = path.split("/")[2]
            try:
                old = load(job_id)
            except Exception:
                self.send_json(404, {"error": "not_found"})
                return
            job = create_job(
                old["request"], async_mode=True, retry_of=job_id,
                dispatch_builder=old.get("dispatch_builder"),
            )
            self.send_json(202, job)
            return
        if path != "/jobs":
            self.send_json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            request = str(body.get("request", "")).strip()
        except Exception:
            body = {}
            request = ""
        if not request:
            self.send_json(400, {"error": "request_required"})
            return
        dispatch_builder, dispatch_error = authenticated_dispatch_route(self.headers, body)
        if dispatch_error:
            code = 400 if dispatch_error == "invalid_dispatch_builder" else 403
            self.send_json(code, {"error": dispatch_error})
            return
        async_mode = urllib.parse.parse_qs(parsed.query).get("async", ["0"])[0].lower() in ("1", "true", "yes")
        continuation = {
            "continuation_enabled": bool(body.get("continuation_enabled", False)),
            "continuation_depth": int(body.get("continuation_depth", 0) or 0),
            "continuation_reason": body.get("continuation_reason"),
            "continuation_request": body.get("continuation_request"),
            "deploy_engineer_runtime": bool(body.get("deploy_engineer_runtime", False)),
            "dispatch_builder": dispatch_builder,
        }
        job = create_job(request, async_mode=async_mode, **continuation)
        self.send_json(202 if async_mode else 200, job)

    def log_message(self, fmt, *args):
        print("agent", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"lifeos-autonomous-agent listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
