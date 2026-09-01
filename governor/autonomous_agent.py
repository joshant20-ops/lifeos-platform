#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import pathlib
import re
import statistics
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(os.environ.get("LIFEOS_AGENT_STATE", "/var/lib/lifeos-agent"))
ROOT.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("LIFEOS_AGENT_PORT", "8790"))
MAX_ITERATIONS = int(os.environ.get("LIFEOS_AGENT_MAX_ITERATIONS", "8"))
BUILDER = os.environ.get("LIFEOS_AGENT_BUILDER", "/usr/local/libexec/lifeos-cloud-builder")
VERIFIER_URL = os.environ.get("LIFEOS_LOCAL_VERIFIER_URL", "http://192.168.0.201:11434/api/generate")
VERIFIER_MODEL = os.environ.get("LIFEOS_LOCAL_VERIFIER_MODEL", "qwen2.5-coder:7b-instruct")
PLATFORM_REPO = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform")).resolve()
UI_PATH = PLATFORM_REPO / "governor" / "agent_ui.html"
RUNTIME_PREFIX = "governor/runtime_jobs/"
MAX_PATCH_BYTES = 1048576
MAX_RUNTIME_BYTES = 65536
REPEATED_FAILURE_LIMIT = int(os.environ.get("LIFEOS_REPEATED_FAILURE_LIMIT", "3"))
STUCK_JOB_MULTIPLIER = float(os.environ.get("LIFEOS_STUCK_JOB_MULTIPLIER", "3.0"))
STUCK_JOB_MIN_SECONDS = int(os.environ.get("LIFEOS_STUCK_JOB_MIN_SECONDS", "300"))
CONTINUATION_MAX_DEPTH = int(os.environ.get("LIFEOS_CONTINUATION_MAX_DEPTH", "4"))
EXECUTION_LOCK = threading.Lock()

# Match actual sensitive-data intent rather than ordinary engineering words.
# In particular, "document the code" must never become local-only merely
# because it contains the substring "document".
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

# Continuation remains outside protected control-plane authority. These terms
# are a conservative fail-closed content gate, not a replacement for the
# root broker, allow-list, verifier, job publisher, or job runner boundaries.
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


def list_jobs(limit=100):
    jobs = []
    for path in sorted(ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
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
    """Return deterministic stuck classifications from persisted job state."""
    jobs = list(jobs if jobs is not None else list_jobs())
    at = at or datetime.now().astimezone()
    history = completed_job_durations(jobs)
    historical_limit = 0.0
    if history:
        # Conservative: require materially longer than both the median and the
        # slowest recent successful job before history alone can call it stuck.
        historical_limit = max(statistics.median(history) * STUCK_JOB_MULTIPLIER, max(history) * 1.5)
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
        if historical_limit:
            item["stuck_reason"] = (
                f"stage has not advanced for {int(age)}s, exceeding conservative threshold "
                f"{int(threshold)}s derived from persisted successful-job duration history"
            )
        else:
            item["stuck_reason"] = (
                f"stage has not advanced for {int(age)}s, exceeding minimum deterministic "
                f"threshold {int(threshold)}s with insufficient successful-job history"
            )
        result.append(item)
    return result


def classify_privacy(text):
    lower = str(text or "").lower()
    return "local-only" if any(re.search(pattern, lower) for pattern in PRIVATE_PATTERNS) else "normal"


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
        "model": VERIFIER_MODEL, "prompt": prompt, "stream": False, "format": "json",
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
        r"(?m)^RUNTIME_RC=.*$", r"(?m)^RESULT=FAIL.*$", r"(?m)^REASON=.*$",
        r"(?m)^DEPLOYMENT_FAILURE=.*$", r"(?m)^PRIVILEGED_BOOTSTRAP_REQUIRED.*$",
        r"(?m)^PI5_PATCH=RETRY.*$", r"(?m)^HANDOFF_ERROR=.*$",
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
    env = os.environ.copy()
    env["LIFEOS_JOB_ID"] = job["id"]
    env["LIFEOS_JOB_PRIVACY"] = job["privacy"]
    args = [BUILDER, job["request"], str(iteration)]
    if verifier_feedback:
        args.append(verifier_feedback)
    cp = subprocess.run(args, text=True, capture_output=True, timeout=1800, env=env)
    raw = (cp.stdout or "") + "\n" + (cp.stderr or "")
    handoff, evidence = parse_handoff(raw)
    return cp.returncode, evidence, handoff


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
    if job["privacy"] == "local-only":
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
        git("reset", "--hard", "origin/main")
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
        try:
            git("reset", "--hard", "origin/main", check=False)
        except Exception:
            pass
        detail = ((exc.stdout or "") + "\n" + (exc.stderr or ""))[-5000:]
        return f"PI5_PATCH=RETRY error=command_failed rc={exc.returncode}\n{detail}\n"
    except Exception as exc:
        return f"PI5_PATCH=RETRY error={type(exc).__name__}:{exc}\n"


def run_pi5_runtime(job, handoff):
    rel = handoff.get("run_script")
    payload = handoff.get("runtime_b64")
    if not rel and not payload:
        return "RUNTIME_ACTION=none_declared\n"
    expected = f"{RUNTIME_PREFIX}{job['id']}.sh"
    if rel != expected:
        return f"RUNTIME_ACTION=rejected_path expected={expected} got={rel}\n"
    if job["privacy"] == "local-only":
        return "RUNTIME_ACTION=blocked_for_cloud_authored_private_job\n"
    if not payload:
        return "RUNTIME_ACTION=missing_payload\n"
    try:
        script = base64.b64decode(payload, validate=True)
    except Exception as exc:
        return f"RUNTIME_ACTION=invalid_base64 error={type(exc).__name__}\n"
    if len(script) > MAX_RUNTIME_BYTES:
        return f"RUNTIME_ACTION=rejected_size size={len(script)}\n"
    text = script.decode("utf-8", errors="strict")
    if not (text.startswith("#!/usr/bin/env bash") or text.startswith("#!/bin/bash")):
        return "RUNTIME_ACTION=rejected_shebang\n"
    runtime_dir = ROOT / "runtime"
    runtime_dir.mkdir(mode=0o750, exist_ok=True)
    target = runtime_dir / f"{job['id']}.sh"
    target.write_text(text)
    target.chmod(0o700)
    cp = subprocess.run(
        ["/usr/bin/timeout", "900s", "/bin/bash", str(target)], cwd=PLATFORM_REPO,
        text=True, capture_output=True, timeout=930,
        env={**os.environ, "LIFEOS_JOB_ID": job["id"], "LIFEOS_JOB_REQUEST": job["request"]},
    )
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    return f"RUNTIME_SCRIPT={rel}\nRUNTIME_RC={cp.returncode}\nPI5_RUNTIME_EVIDENCE:\n{out[-16000:]}\n"


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
        evidence = f"BUILD_EVIDENCE:\n{build_evidence[-12000:]}\n\nPUBLICATION_EVIDENCE:\n{publication[-7000:]}\n\n{runtime}"
        rec["evidence"] = evidence[-26000:]

        set_stage(job, "verifier", f"iteration {iteration}: local Qwen verification")
        try:
            verdict = local_verify(job, iteration, rec["evidence"])
        except Exception as exc:
            verdict = {"verdict": "RETRY", "reason": f"local verifier unavailable: {type(exc).__name__}", "next_instruction": "Retry local verifier and runtime verification."}
        rec["verification"] = verdict
        rec["finished_at"] = now()
        signature = failure_signature(rec["evidence"], verdict)
        if signature:
            rec["failure_signature"] = signature
        job.setdefault("iterations", []).append(rec)
        v = str(verdict.get("verdict", "RETRY")).upper()

        if v == "PASS":
            job["status"] = "PASS"
            job["completed_at"] = now()
            set_stage(job, "complete", "local verifier accepted result")
            return job
        if v == "BLOCKED":
            job["status"] = "BLOCKED"
            job["blocked_reason"] = verdict.get("reason")
            job["completed_at"] = now()
            set_stage(job, "blocked", job["blocked_reason"])
            return job

        repeat_count = update_failure_history(job, signature)
        if repeat_count >= REPEATED_FAILURE_LIMIT:
            job["status"] = "BLOCKED"
            job["blocked_reason"] = (
                f"repeated deterministic failure detected ({repeat_count} occurrences); "
                "stopped before exhausting the full iteration budget"
            )
            job["completed_at"] = now()
            set_stage(job, "blocked_repeated_failure", job["blocked_reason"])
            return job

        base_feedback = str(verdict.get("next_instruction") or verdict.get("reason") or "Verification failed; continue toward the original goal using the evidence.")
        if repeat_count >= 2:
            feedback = (
                f"REPLAN REQUIRED: failure signature {signature} repeated {repeat_count} times. "
                "Do not repeat the previous implementation/runtime approach. Diagnose the deterministic cause and choose a materially different plan. " + base_feedback
            )
        else:
            feedback = base_feedback
        set_stage(job, "retry_planning", f"iteration {iteration} failed; preparing next plan")
        save(job)

    job["status"] = "BLOCKED"
    job["blocked_reason"] = "maximum iterations reached"
    job["completed_at"] = now()
    set_stage(job, "blocked", job["blocked_reason"])
    return job


def continuation_allowed(job):
    """Fail closed unless a successful job explicitly opted into a bounded next step."""
    if not bool(job.get("continuation_enabled")):
        return False
    if str(job.get("status") or "").upper() != "PASS":
        return False
    depth = int(job.get("continuation_depth") or 0)
    if depth >= CONTINUATION_MAX_DEPTH:
        return False
    request = str(job.get("continuation_request") or "").strip()
    if not request:
        return False
    lower = request.lower()
    if any(term in lower for term in PROTECTED_CONTINUATION_TERMS):
        return False
    # BLOCKED jobs and repeated deterministic failure never reach here because
    # only PASS is eligible. The verifier therefore retains stop authority.
    return True


def spawn_continuation(job):
    """Create the child only after the parent has released EXECUTION_LOCK."""
    if not continuation_allowed(job):
        return None
    child = new_job(
        str(job["continuation_request"]),
        continuation_enabled=True,
        continuation_parent=job["id"],
        continuation_depth=int(job.get("continuation_depth") or 0) + 1,
        continuation_reason=str(job.get("continuation_reason") or "explicit bounded continuation"),
    )
    job = load(job["id"])
    job["continuation_child"] = child["id"]
    save(job)
    threading.Thread(target=execute_job, args=(child,), daemon=True, name=f"job-{child['id']}").start()
    return child


def execute_job(job):
    with EXECUTION_LOCK:
        final = _execute_job_locked(job)
    # Event-driven continuation is deliberately outside the execution lock so
    # the child can acquire it; there is no hourly polling dependency here.
    spawn_continuation(final)


def new_job(request, retry_of=None, continuation_enabled=False, continuation_parent=None,
            continuation_depth=0, continuation_reason=None, continuation_request=None):
    job = {
        "id": uuid.uuid4().hex[:12], "created_at": now(), "request": request.strip(),
        "privacy": classify_privacy(request), "status": "QUEUED", "stage": "queued",
        "stage_changed_at": now(), "iterations": [], "repeated_failure_count": 0,
        "continuation_enabled": bool(continuation_enabled),
        "continuation_depth": int(continuation_depth or 0),
    }
    if retry_of:
        job["retry_of"] = retry_of
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
                "service": "lifeos-autonomous-agent", "status": "ok", "max_iterations": MAX_ITERATIONS,
                "repeated_failure_limit": REPEATED_FAILURE_LIMIT, "stuck_job_multiplier": STUCK_JOB_MULTIPLIER,
                "continuation_max_depth": CONTINUATION_MAX_DEPTH, "runtime_controller": "pi5",
                "git_controller": "pi5", "ui": "/"
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
            )
            summaries = [{k: j.get(k) for k in keys if k in j} for j in jobs]
            self.send_json(200, {"jobs": summaries})
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
            job = create_job(old["request"], async_mode=True, retry_of=job_id)
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
        async_mode = urllib.parse.parse_qs(parsed.query).get("async", ["0"])[0].lower() in ("1", "true", "yes")
        continuation = {
            "continuation_enabled": bool(body.get("continuation_enabled", False)),
            "continuation_depth": int(body.get("continuation_depth", 0) or 0),
            "continuation_reason": body.get("continuation_reason"),
            "continuation_request": body.get("continuation_request"),
        }
        job = create_job(request, async_mode=async_mode, **continuation)
        self.send_json(202 if async_mode else 200, job)

    def log_message(self, fmt, *args):
        print("agent", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"lifeos-autonomous-agent listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
