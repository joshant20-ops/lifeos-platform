#!/usr/bin/env python3
import json
import os
import pathlib
import re
import subprocess
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(os.environ.get("LIFEOS_AGENT_STATE", "/var/lib/lifeos-agent"))
ROOT.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("LIFEOS_AGENT_PORT", "8790"))
MAX_ITERATIONS = int(os.environ.get("LIFEOS_AGENT_MAX_ITERATIONS", "8"))
BUILDER = os.environ.get("LIFEOS_AGENT_BUILDER", "/usr/local/libexec/lifeos-cloud-builder")
VERIFIER_URL = os.environ.get("LIFEOS_LOCAL_VERIFIER_URL", "http://192.168.0.201:11434/api/generate")
VERIFIER_MODEL = os.environ.get("LIFEOS_LOCAL_VERIFIER_MODEL", "qwen2.5-coder:7b-instruct")
PLATFORM_REPO = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform")).resolve()
RUNTIME_PREFIX = "governor/runtime_jobs/"

PRIVATE_TERMS = {
    "paperless", "document", "documents", "private data", "personal data",
    "email", "emails", "medical", "bank", "statement", "invoice", "passport",
}


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def job_path(job_id):
    return ROOT / f"{job_id}.json"


def save(job):
    tmp = job_path(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2, sort_keys=True))
    os.replace(tmp, job_path(job["id"]))


def load(job_id):
    return json.loads(job_path(job_id).read_text())


def classify_privacy(text):
    lower = text.lower()
    return "local-only" if any(term in lower for term in PRIVATE_TERMS) else "normal"


def local_verify(job, iteration, evidence):
    prompt = f"""You are the independent LOCAL verifier for LifeOS.
Decide whether the user's original goal is actually complete from supplied BUILD AND RUNTIME evidence.
Return JSON only with keys: verdict, reason, next_instruction.
verdict must be PASS, RETRY, or BLOCKED.

Rules:
- PASS only when evidence demonstrates the requested outcome works.
- RETRY when there is any actionable engineering, deployment, configuration, testing, or repair step that the autonomous system can attempt itself.
- BLOCKED is reserved for a genuinely external blocker the autonomous system cannot resolve itself, such as missing user-only credentials, unavailable required hardware, a required physical action, or a safety policy prohibition.
- Unrelated pre-existing repository test failures are NOT a blocker for a scoped job; mention them if relevant but judge the user's requested outcome from scoped evidence.
- A builder saying RESULT=BLOCKED does not force you to choose BLOCKED. If its reason is internally actionable, choose RETRY and specify the next action.
- Do not ask the user to run diagnostic commands that the Pi5/Engineer/TowerPC automation can run itself.
- Do not assume success merely because a script exited zero.

User goal: {job['request']}
Privacy class: {job['privacy']}
Iteration: {iteration}
Evidence:\n{evidence[-16000:]}
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
        return {"verdict": "RETRY", "reason": "verifier returned invalid JSON", "next_instruction": "Re-run focused verification and return valid JSON evidence."}


def run_builder(job, iteration, verifier_feedback=None):
    env = os.environ.copy()
    env["LIFEOS_JOB_ID"] = job["id"]
    env["LIFEOS_JOB_PRIVACY"] = job["privacy"]
    args = [BUILDER, job["request"], str(iteration)]
    if verifier_feedback:
        args.append(verifier_feedback)
    cp = subprocess.run(args, text=True, capture_output=True, timeout=1800, env=env)
    evidence = (cp.stdout or "") + "\n" + (cp.stderr or "")
    return cp.returncode, evidence


def runtime_path_from_evidence(job, evidence):
    matches = re.findall(r"(?m)^RUN_SCRIPT=([^\s]+)\s*$", evidence)
    if not matches:
        return None
    rel = matches[-1].strip()
    expected = f"{RUNTIME_PREFIX}{job['id']}.sh"
    if rel != expected:
        raise RuntimeError(f"runtime path rejected: expected {expected}, got {rel}")
    return rel


def run_pi5_runtime(job, evidence):
    rel = runtime_path_from_evidence(job, evidence)
    if rel is None:
        return "RUNTIME_ACTION=none_declared\n"
    if job["privacy"] == "local-only":
        return "RUNTIME_ACTION=blocked_for_cloud_authored_private_job\n"

    subprocess.run(["git", "fetch", "origin", "main"], cwd=PLATFORM_REPO, check=True, text=True, capture_output=True, timeout=120)
    show = subprocess.run(
        ["git", "show", f"origin/main:{rel}"],
        cwd=PLATFORM_REPO,
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
    script = show.stdout
    if not script.startswith("#!/usr/bin/env bash") and not script.startswith("#!/bin/bash"):
        raise RuntimeError("runtime script rejected: bash shebang required")
    if len(script.encode()) > 65536:
        raise RuntimeError("runtime script rejected: exceeds 64KiB")

    runtime_dir = ROOT / "runtime"
    runtime_dir.mkdir(mode=0o750, exist_ok=True)
    target = runtime_dir / f"{job['id']}.sh"
    target.write_text(script)
    target.chmod(0o700)

    cp = subprocess.run(
        ["/usr/bin/timeout", "900s", "/bin/bash", str(target)],
        cwd=PLATFORM_REPO,
        text=True,
        capture_output=True,
        timeout=930,
        env={**os.environ, "LIFEOS_JOB_ID": job["id"], "LIFEOS_JOB_REQUEST": job["request"]},
    )
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    return f"RUNTIME_SCRIPT={rel}\nRUNTIME_RC={cp.returncode}\nRUNTIME_EVIDENCE:\n{out[-16000:]}\n"


def execute_job(job):
    job["status"] = "RUNNING"
    save(job)
    feedback = None
    for iteration in range(1, MAX_ITERATIONS + 1):
        rec = {"iteration": iteration, "started_at": now()}
        try:
            rc, build_evidence = run_builder(job, iteration, feedback)
            rec["builder_rc"] = rc
        except Exception as exc:
            rc = 255
            build_evidence = f"builder exception: {type(exc).__name__}: {exc}"
            rec["builder_rc"] = rc

        try:
            runtime_evidence = run_pi5_runtime(job, build_evidence)
        except Exception as exc:
            runtime_evidence = f"RUNTIME_EXCEPTION={type(exc).__name__}: {exc}\n"

        evidence = f"BUILD_EVIDENCE:\n{build_evidence[-16000:]}\n\n{runtime_evidence}"
        rec["evidence"] = evidence[-24000:]

        try:
            verdict = local_verify(job, iteration, rec["evidence"])
        except Exception as exc:
            verdict = {"verdict": "RETRY", "reason": f"local verifier unavailable: {type(exc).__name__}", "next_instruction": "Retry local verifier and runtime verification."}
        rec["verification"] = verdict
        rec["finished_at"] = now()
        job.setdefault("iterations", []).append(rec)
        v = str(verdict.get("verdict", "RETRY")).upper()
        if v == "PASS":
            job["status"] = "PASS"
            job["completed_at"] = now()
            save(job)
            return
        if v == "BLOCKED":
            job["status"] = "BLOCKED"
            job["blocked_reason"] = verdict.get("reason")
            save(job)
            return
        feedback = str(verdict.get("next_instruction") or verdict.get("reason") or "Verification failed; inspect evidence and continue toward the original goal.")
        save(job)
    job["status"] = "BLOCKED"
    job["blocked_reason"] = "maximum iterations reached"
    save(job)


def create_job(request):
    job = {
        "id": uuid.uuid4().hex[:12],
        "created_at": now(),
        "request": request.strip(),
        "privacy": classify_privacy(request),
        "status": "QUEUED",
        "iterations": [],
    }
    save(job)
    execute_job(job)
    return job


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, payload):
        data = json.dumps(payload, sort_keys=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"service": "lifeos-autonomous-agent", "status": "ok", "max_iterations": MAX_ITERATIONS, "runtime_controller": "pi5"})
            return
        if self.path.startswith("/jobs/"):
            job_id = self.path.split("/", 2)[2]
            try:
                self.send_json(200, load(job_id))
            except Exception:
                self.send_json(404, {"error": "not_found"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/jobs":
            self.send_json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            request = str(body.get("request", "")).strip()
        except Exception:
            request = ""
        if not request:
            self.send_json(400, {"error": "request_required"})
            return
        job = create_job(request)
        self.send_json(200, job)

    def log_message(self, fmt, *args):
        print("agent", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"lifeos-autonomous-agent listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
