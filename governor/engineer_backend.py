#!/usr/bin/env python3
import json
import os
import re
import statistics
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("LIFEOS_ENGINEER_PORT", "8793"))
AGENT_URL = os.environ.get("LIFEOS_AGENT_URL", "http://127.0.0.1:8790")
OLLAMA_URL = os.environ.get("LIFEOS_ENGINEER_MODEL_URL", "http://192.168.0.201:11434/api/generate")
OLLAMA_MODEL = os.environ.get("LIFEOS_ENGINEER_MODEL", "qwen2.5-coder:7b-instruct")
MODEL_ID = "lifeos-engineer"
APPROVALS = {"run it", "go ahead", "do it", "yes run it", "yes, run it", "approved", "approve", "proceed"}
PROPOSAL_REF_RE = re.compile(r"proposal ref\s*:?\s*`?([a-f0-9]{10})`?", re.I)
JOB_TEXT_RE = re.compile(r"(?:engineering\s+job|job)\s+`?([a-f0-9]{12})`?", re.I)
PROPOSALS = {}
MAX_PROPOSALS = 128

SYSTEM = """You are LifeOS Engineer, the local technical engineering manager for Joshan's homelab and LifeOS platform.
You are a collaborative senior engineer, not a command parser and not the cloud coding builder.

Your job is to understand the desired outcome, inspect the supplied LOCAL read-only context, challenge weak assumptions when useful, and prepare a precise natural-language execution brief for the autonomous Pi5 engineering agent and Codex builder.

Rules:
- Use LOCAL CONTEXT as evidence. Never claim you inspected something that is not present there.
- If a previous job failed, explain the concrete failure evidence before proposing another job.
- Never invent CLI commands, service flags, API endpoints, file paths, or capabilities. The Codex builder discovers implementation details after approval.
- proposed_job must be a natural-language engineering brief containing goals, constraints, acceptance criteria, safety/privacy requirements and known evidence. Do not return a command plan or JSON object as proposed_job.
- Listen for the outcome the user actually wants.
- Restate your understanding when ambiguity exists or the task is substantial.
- Ask a clarifying question only when the answer materially changes implementation, safety, cost, privacy or reversibility.
- Propose up to four genuinely useful improvements, safeguards or tests. Do not add busywork.
- Prefer robust, observable, reversible changes and reuse existing LifeOS architecture.
- Never say work has been executed unless runtime evidence says so.
- Do not expose secrets, credentials, private documents, emails, financial/medical data or Home Assistant private history to cloud Codex.
- Private runtime discovery happens locally; only a redacted technical brief may be sent to the cloud builder.
- Execution always requires a separate explicit user approval.

Return JSON only with keys:
reply: concise natural conversational reply.
understanding: one-sentence desired outcome.
needs_clarification: boolean.
clarifying_question: string or empty.
improvements: array of maximum four short strings.
ready_to_run: boolean.
proposed_job: complete natural-language engineering brief string, or empty when not ready.
"""


def request_json(url, payload=None, timeout=180):
    if payload is None:
        req = urllib.request.Request(url, method="GET")
    else:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def clean_text(text):
    return str(text or "").strip()


def explicit_approval(text):
    clean = re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()
    return clean in APPROVALS


def proposal_ref(messages):
    for item in reversed(messages[:-1]):
        if item.get("role") != "assistant":
            continue
        m = PROPOSAL_REF_RE.search(clean_text(item.get("content")))
        if m:
            return m.group(1)
    return None


def last_job_id(messages):
    for item in reversed(messages):
        m = JOB_TEXT_RE.search(clean_text(item.get("content")))
        if m:
            return m.group(1)
    return None


def _intent_text(text):
    return re.sub(r"[^a-z0-9' ]+", " ", clean_text(text).lower()).strip()


def asks_history(text):
    clean = _intent_text(text)
    return any(phrase in clean for phrase in ("historical jobs", "all jobs", "job history"))


def asks_queue(text):
    clean = _intent_text(text)
    return any(phrase in clean for phrase in (
        "what jobs are currently running", "what is queued", "queue status",
        "running queued", "failed blocked", "jobs currently running",
    ))


def asks_stuck_jobs(text):
    clean = _intent_text(text)
    return any(phrase in clean for phrase in (
        "is anything stuck", "any job stuck", "any jobs stuck", "stuck jobs",
        "what is stuck", "what's stuck",
    ))


def asks_status(text):
    clean = _intent_text(text)
    phrases = (
        "status", "progress", "eta", "how long", "what's it doing", "what is it doing",
        "what is it actually doing", "what's it actually doing", "is it stuck", "stuck",
        "current stage", "progress report", "job report", "how is it going", "how's it going",
    )
    return any(p in clean for p in phrases)


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None


def human_duration(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m" if sec < 15 else f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def history_durations():
    try:
        jobs = request_json(AGENT_URL + "/jobs", timeout=5).get("jobs", [])
    except Exception:
        return []
    durations = []
    for job in jobs:
        if job.get("status") not in ("PASS", "BLOCKED"):
            continue
        start = parse_time(job.get("started_at") or job.get("created_at"))
        end = parse_time(job.get("completed_at"))
        if start and end and end >= start:
            durations.append((end - start).total_seconds())
    return durations[:20]


def evidence_summary(job):
    iterations = job.get("iterations", []) or []
    if not iterations:
        return ""
    last = iterations[-1]
    evidence = clean_text(last.get("evidence"))
    verification = last.get("verification") or {}
    signals = []
    for pattern in (
        r"(?m)^RUNTIME_RC=.*$",
        r"(?m)^RESULT=FAIL.*$",
        r"(?m)^DEPLOYMENT_FAILURE=.*$",
        r"(?m)^PRIVILEGED_BOOTSTRAP_REQUIRED.*$",
        r"(?m)^PI5_PATCH=RETRY.*$",
        r"(?m)^HANDOFF_ERROR=.*$",
    ):
        matches = re.findall(pattern, evidence)
        if matches:
            signals.append(matches[-1])
    reason = clean_text(verification.get("reason"))
    if reason:
        signals.append("Verifier: " + reason[:700])
    return " | ".join(signals[:4])


def status_reply(job):
    status = clean_text(job.get("status") or "UNKNOWN")
    job_id = clean_text(job.get("id"))
    stage = clean_text(job.get("stage") or "unknown")
    iterations = job.get("iterations", []) or []
    start = parse_time(job.get("started_at") or job.get("created_at"))
    end = parse_time(job.get("completed_at")) or datetime.now().astimezone()
    elapsed = human_duration((end - start).total_seconds()) if start else "unknown"
    parts = [f"Job `{job_id}` is **{status}**. Stage: **{stage}**. Elapsed: **{elapsed}**. Iterations completed: **{len(iterations)}**."]

    signal = evidence_summary(job)
    if signal:
        parts.append("Latest evidence: " + signal)

    if status == "QUEUED":
        parts.append("It is waiting for the engineering execution slot.")
    elif status == "RUNNING":
        durations = history_durations()
        if durations and start:
            median = statistics.median(durations)
            elapsed_seconds = max(0, (datetime.now().astimezone() - start).total_seconds())
            remaining = max(0, median - elapsed_seconds)
            low = max(0, min(durations) - elapsed_seconds)
            high = max(0, max(durations) - elapsed_seconds)
            parts.append(f"ETA estimate from recent completed jobs: about **{human_duration(remaining)} remaining**, rough range **{human_duration(low)}–{human_duration(high)}**. This is an estimate, not a guarantee.")
        else:
            parts.append("There is not enough completed-job history for a defensible ETA yet.")
    elif status == "PASS":
        parts.append("The local verifier accepted the result.")
    elif status == "BLOCKED":
        reason = clean_text(job.get("blocked_reason") or "The job is blocked and needs attention.")
        parts.append("Blocked reason: " + reason)
        repeat = job.get("repeated_failure_count")
        if repeat:
            parts.append(f"The same deterministic failure signature was seen {repeat} times.")
    return " ".join(parts)


def _job_line(job):
    fields = ("id", "status", "stage", "created_at", "started_at", "completed_at", "request")
    values = []
    for field in fields:
        value = job.get(field)
        if value is not None and value != "":
            values.append(f"{field}={clean_text(value)}")
    return " | ".join(values)


def jobs_history_reply():
    jobs = request_json(AGENT_URL + "/jobs", timeout=10).get("jobs", [])
    if not jobs:
        return "No LifeOS Engineer jobs are present in the agent job database."
    return "Historical LifeOS Engineer jobs (newest first):\n" + "\n".join(f"- {_job_line(job)}" for job in jobs)


def jobs_queue_reply():
    jobs = request_json(AGENT_URL + "/jobs", timeout=10).get("jobs", [])
    groups = {"RUNNING": [], "QUEUED": [], "BLOCKED/FAILED": [], "COMPLETE": []}
    for job in jobs:
        status = clean_text(job.get("status")).upper()
        if status == "RUNNING":
            group = "RUNNING"
        elif status in ("QUEUED", "PENDING", "STAGING"):
            group = "QUEUED"
        elif status in ("BLOCKED", "FAIL", "FAILED", "ERROR"):
            group = "BLOCKED/FAILED"
        elif status in ("PASS", "COMPLETE", "COMPLETED"):
            group = "COMPLETE"
        else:
            group = "BLOCKED/FAILED"
        groups[group].append(job)
    lines = ["LifeOS Engineer queue from the agent job database:"]
    for name in ("RUNNING", "QUEUED", "BLOCKED/FAILED", "COMPLETE"):
        items = groups[name]
        lines.append(f"{name} ({len(items)}):")
        lines.extend(f"- {_job_line(job)}" for job in items) if items else lines.append("- none")
    return "\n".join(lines)


def jobs_stuck_reply():
    payload = request_json(AGENT_URL + "/jobs/stuck", timeout=10)
    stuck = payload.get("stuck_jobs", []) or []
    if not stuck:
        return "No jobs are deterministically classified as stuck by the LifeOS agent right now."
    lines = [f"Deterministically stuck LifeOS Engineer jobs ({len(stuck)}):"]
    for job in stuck:
        reason = clean_text(job.get("stuck_reason") or "stuck threshold exceeded")
        lines.append(f"- {_job_line(job)} | stuck_reason={reason}")
    return "\n".join(lines)


def local_context(messages):
    context = {"repository": {}, "recent_job": None}
    try:
        context["repository"] = request_json(AGENT_URL + "/context", timeout=5)
    except Exception as exc:
        context["repository"] = {"status": "unavailable", "detail": type(exc).__name__}
    job_id = last_job_id(messages)
    if job_id:
        try:
            job = request_json(AGENT_URL + "/jobs/" + job_id, timeout=5)
            iterations = job.get("iterations", []) or []
            last = iterations[-1] if iterations else {}
            context["recent_job"] = {
                "id": job.get("id"),
                "status": job.get("status"),
                "stage": job.get("stage"),
                "created_at": job.get("created_at"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "blocked_reason": job.get("blocked_reason"),
                "iteration_count": len(iterations),
                "latest_verification": last.get("verification"),
                "latest_evidence_summary": evidence_summary(job),
                "repeated_failure_count": job.get("repeated_failure_count"),
            }
        except Exception as exc:
            context["recent_job"] = {"id": job_id, "status": "unavailable", "detail": type(exc).__name__}
    return context


def normalise_proposal(value):
    if not isinstance(value, str):
        return ""
    proposal = value.strip()
    if not proposal:
        return ""
    forbidden = (
        "lifeos-autonomous-agent --",
        "sudo ",
        "curl -",
        "ssh ",
    )
    if any(token in proposal.lower() for token in forbidden):
        return ""
    return proposal


def store_proposal(proposal):
    ref = uuid.uuid4().hex[:10]
    PROPOSALS[ref] = {"proposal": proposal, "created": time.time()}
    if len(PROPOSALS) > MAX_PROPOSALS:
        oldest = sorted(PROPOSALS.items(), key=lambda kv: kv[1]["created"])[: len(PROPOSALS) - MAX_PROPOSALS]
        for key, _ in oldest:
            PROPOSALS.pop(key, None)
    return ref


def analyse(messages):
    transcript = []
    for item in messages[-14:]:
        role = clean_text(item.get("role") or "user")[:16].upper()
        content = clean_text(item.get("content"))[:7000]
        transcript.append(f"{role}: {content}")
    context = local_context(messages)
    prompt = SYSTEM + "\n\nLOCAL READ-ONLY CONTEXT:\n" + json.dumps(context, indent=2)[:10000]
    prompt += "\n\nConversation:\n" + "\n".join(transcript) + "\n\nReturn JSON now."
    result = request_json(OLLAMA_URL, {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.15, "num_ctx": 12288},
    })
    parsed = json.loads(result.get("response", "{}"))
    improvements = [clean_text(x) for x in parsed.get("improvements", []) if clean_text(x)][:4]
    reply = clean_text(parsed.get("reply"))
    question = clean_text(parsed.get("clarifying_question"))
    understanding = clean_text(parsed.get("understanding"))
    ready = bool(parsed.get("ready_to_run", False))
    proposal = normalise_proposal(parsed.get("proposed_job"))

    blocks = [reply] if reply else []
    if understanding and understanding.lower() not in reply.lower():
        blocks.append(f"**My understanding:** {understanding}")
    if improvements:
        blocks.append("**Improvements I'd include:**\n" + "\n".join(f"- {x}" for x in improvements))
    if bool(parsed.get("needs_clarification", False)) and question:
        blocks.append(question)
    if ready:
        if proposal:
            ref = store_proposal(proposal)
            blocks.append(f"If that matches what you want, say **run it**. Proposal ref: `{ref}`.")
        else:
            blocks.append("I have enough intent to continue, but the generated execution brief failed safety/schema validation. I won't queue it until I can produce a clean natural-language brief.")
    return "\n\n".join(blocks).strip()


def engineer_reply(messages):
    latest = clean_text(messages[-1].get("content")) if messages else ""
    if explicit_approval(latest):
        ref = proposal_ref(messages)
        record = PROPOSALS.get(ref) if ref else None
        if not record:
            return "The approved proposal is no longer available in server-side state, so I won't regenerate or change it silently. Please restate the task and I'll produce a fresh proposal for approval."
        job = request_json(AGENT_URL + "/jobs?async=1", {"request": record["proposal"]}, timeout=15)
        return (f"Queued it as engineering job `{job['id']}`. The Pi5 runtime and local verifier are the source of truth. "
                f"Ask me for status, ETA, what it's doing, or whether it looks stuck.")
    if asks_history(latest):
        return jobs_history_reply()
    if asks_queue(latest):
        return jobs_queue_reply()
    if asks_stuck_jobs(latest):
        return jobs_stuck_reply()
    if asks_status(latest):
        job_id = last_job_id(messages)
        if not job_id:
            return "There isn't a LifeOS engineering job attached to this conversation yet."
        return status_reply(request_json(AGENT_URL + "/jobs/" + job_id, timeout=10))
    return analyse(messages)


def completion_payload(content):
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/health", "/v1/health"):
            try:
                agent = request_json(AGENT_URL + "/health", timeout=5)
                if agent.get("status") != "ok":
                    raise RuntimeError("agent_not_ready")
                request_json(OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags", timeout=5)
                self.send_json(200, {"service": "lifeos-engineer", "status": "ok", "agent": agent.get("status"), "model": OLLAMA_MODEL, "chat_state": "server_side"})
            except Exception as exc:
                self.send_json(503, {"service": "lifeos-engineer", "status": "degraded", "detail": type(exc).__name__})
            return
        if path == "/v1/models":
            self.send_json(200, {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "lifeos"}]})
            return
        self.send_json(404, {"error": {"message": "not_found", "type": "not_found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_json(404, {"error": {"message": "not_found", "type": "not_found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            messages = body.get("messages", [])
            if not isinstance(messages, list) or not messages:
                self.send_json(400, {"error": {"message": "messages_required", "type": "invalid_request_error"}})
                return
            content = engineer_reply(messages)
            if body.get("stream"):
                cid = "chatcmpl-" + uuid.uuid4().hex
                chunks = [
                    {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": MODEL_ID,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]},
                    {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": MODEL_ID,
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
                return
            self.send_json(200, completion_payload(content))
        except Exception as exc:
            self.send_json(502, {"error": {"message": f"engineer_backend:{type(exc).__name__}", "type": "upstream_error"}})

    def log_message(self, fmt, *args):
        print("engineer", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"lifeos-engineer OpenAI-compatible backend listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
