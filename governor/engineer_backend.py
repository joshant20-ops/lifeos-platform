#!/usr/bin/env python3
import base64
import json
import os
import re
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("LIFEOS_ENGINEER_PORT", "8793"))
AGENT_URL = os.environ.get("LIFEOS_AGENT_URL", "http://127.0.0.1:8790")
OLLAMA_URL = os.environ.get("LIFEOS_ENGINEER_MODEL_URL", "http://192.168.0.201:11434/api/generate")
OLLAMA_MODEL = os.environ.get("LIFEOS_ENGINEER_MODEL", "qwen2.5-coder:7b-instruct")
MODEL_ID = "lifeos-engineer"
PROPOSAL_RE = re.compile(r"<!--LIFEOS_PROPOSAL:([A-Za-z0-9+/=]+)-->")
JOB_RE = re.compile(r"<!--LIFEOS_JOB:([a-f0-9]{12})-->")
APPROVALS = {"run it", "go ahead", "do it", "yes run it", "yes, run it", "approved", "approve", "proceed"}
STATUS_WORDS = {"status", "progress", "how is it going", "how's it going", "what's the status"}

SYSTEM = """You are LifeOS Engineer, the technical engineering AI for Joshan's homelab and LifeOS platform.
You are a collaborative senior engineer, not a command parser.

Your job is to understand the desired outcome before execution, challenge weak assumptions when useful, propose better engineering approaches, and prepare a precise execution brief for the autonomous Pi5 engineering agent.

Rules:
- Listen for the outcome the user actually wants.
- Restate your understanding when ambiguity exists or the task is substantial.
- Ask a clarifying question only when the answer materially changes implementation, safety, cost, privacy or reversibility.
- Propose up to four genuinely useful improvements, safeguards or tests. Do not add busywork.
- Prefer robust, observable, reversible changes and reuse existing LifeOS architecture.
- Never say work has been executed unless runtime evidence says so.
- Do not expose secrets, credentials, private documents, emails, financial/medical data or Home Assistant private history to cloud Codex.
- Private runtime discovery should happen locally and only a redacted technical brief should be sent to the engineering builder.
- When intent is sufficiently clear, produce a self-contained engineering brief. Execution will require a separate explicit user approval.

Return JSON only with keys:
reply: concise natural conversational reply.
understanding: one-sentence desired outcome.
needs_clarification: boolean.
clarifying_question: string or empty.
improvements: array of maximum four short strings.
ready_to_run: boolean.
proposed_job: complete self-contained engineering brief, or empty when not ready.
"""


def request_json(url, payload=None, timeout=180):
    if payload is None:
        req = urllib.request.Request(url, method="GET")
    else:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def strip_markers(text):
    return PROPOSAL_RE.sub("", JOB_RE.sub("", text or "")).strip()


def encode_proposal(text):
    return base64.b64encode(text.encode()).decode()


def decode_last_proposal(messages):
    for item in reversed(messages[:-1]):
        if item.get("role") != "assistant":
            continue
        m = PROPOSAL_RE.search(str(item.get("content", "")))
        if m:
            try:
                return base64.b64decode(m.group(1), validate=True).decode()
            except Exception:
                return None
    return None


def last_job_id(messages):
    for item in reversed(messages):
        m = JOB_RE.search(str(item.get("content", "")))
        if m:
            return m.group(1)
    return None


def explicit_approval(text):
    clean = re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()
    return clean in APPROVALS


def asks_status(text):
    clean = re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()
    return clean in STATUS_WORDS or clean.startswith("status ") or "job status" in clean


def status_reply(job):
    status = str(job.get("status", "UNKNOWN"))
    iterations = job.get("iterations", []) or []
    parts = [f"Job `{job.get('id')}` is **{status}**."]
    if status == "QUEUED":
        parts.append("It is waiting for the engineering execution slot.")
    elif status == "RUNNING":
        parts.append(f"It has completed {len(iterations)} verification iteration(s) so far.")
    elif status == "PASS":
        reason = ""
        if iterations:
            reason = str(iterations[-1].get("verification", {}).get("reason", "")).strip()
        parts.append("The local verifier accepted the result." + (f" {reason}" if reason else ""))
    elif status == "BLOCKED":
        parts.append(str(job.get("blocked_reason") or "The job is blocked and needs attention."))
    return " ".join(parts) + f"\n\n<!--LIFEOS_JOB:{job.get('id')}-->"


def analyse(messages):
    transcript = []
    for item in messages[-14:]:
        role = str(item.get("role", "user"))[:16].upper()
        content = strip_markers(str(item.get("content", "")))[:7000]
        transcript.append(f"{role}: {content}")
    prompt = SYSTEM + "\n\nConversation:\n" + "\n".join(transcript) + "\n\nReturn JSON now."
    result = request_json(OLLAMA_URL, {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": 8192},
    })
    raw = result.get("response", "{}")
    parsed = json.loads(raw)
    improvements = [str(x).strip() for x in parsed.get("improvements", []) if str(x).strip()][:4]
    reply = str(parsed.get("reply", "")).strip()
    question = str(parsed.get("clarifying_question", "")).strip()
    understanding = str(parsed.get("understanding", "")).strip()
    ready = bool(parsed.get("ready_to_run", False))
    proposal = str(parsed.get("proposed_job", "")).strip()

    blocks = [reply] if reply else []
    if understanding and understanding.lower() not in reply.lower():
        blocks.append(f"**My understanding:** {understanding}")
    if improvements:
        blocks.append("**Improvements I'd include:**\n" + "\n".join(f"- {x}" for x in improvements))
    if bool(parsed.get("needs_clarification", False)) and question:
        blocks.append(question)
    if ready and proposal:
        blocks.append("If that matches what you want, say **run it**. I won't execute it before explicit approval.")
        blocks.append(f"<!--LIFEOS_PROPOSAL:{encode_proposal(proposal)}-->")
    return "\n\n".join(blocks).strip()


def engineer_reply(messages):
    latest = str(messages[-1].get("content", "")).strip() if messages else ""
    if explicit_approval(latest):
        proposal = decode_last_proposal(messages)
        if not proposal:
            return "I don't have an approved engineering brief in this conversation yet. Tell me what you want changed first."
        job = request_json(AGENT_URL + "/jobs?async=1", {"request": proposal}, timeout=15)
        return (f"Queued it as engineering job `{job['id']}`. I'll treat the Pi5 runtime and local verifier as the source of truth for completion. "
                f"Ask me for **status** and I'll check it.\n\n<!--LIFEOS_JOB:{job['id']}-->")
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
        if self.path in ("/health", "/v1/health"):
            try:
                agent = request_json(AGENT_URL + "/health", timeout=5)
                request_json(OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/tags", timeout=5)
                self.send_json(200, {"service": "lifeos-engineer", "status": "ok", "agent": agent.get("status"), "model": OLLAMA_MODEL})
            except Exception as exc:
                self.send_json(503, {"service": "lifeos-engineer", "status": "degraded", "detail": type(exc).__name__})
            return
        if self.path == "/v1/models":
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
