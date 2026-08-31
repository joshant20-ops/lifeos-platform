#!/usr/bin/env python3
import json
import os
import pathlib
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("LIFEOS_ASSISTANT_PORT", "8791"))
AGENT_URL = os.environ.get("LIFEOS_AGENT_URL", "http://127.0.0.1:8790")
OLLAMA_URL = os.environ.get("LIFEOS_ASSISTANT_MODEL_URL", "http://192.168.0.201:11434/api/generate")
OLLAMA_MODEL = os.environ.get("LIFEOS_ASSISTANT_MODEL", "qwen2.5-coder:7b-instruct")
UI_PATH = pathlib.Path(os.environ.get("LIFEOS_ASSISTANT_UI", "/home/joshan/lifeos-platform/governor/assistant_ui.html"))

SYSTEM = """You are the conversational front door to the LifeOS autonomous engineering agent.
Your job is to understand what Joshan wants before creating an engineering job.

Behave like a capable technical partner rather than a command parser:
- Listen for the actual outcome the user wants, not just their literal wording.
- Briefly restate your understanding when that reduces ambiguity.
- Ask a clarifying question only when a missing answer materially changes the implementation or risk.
- Propose useful improvements, checks, safeguards or better approaches when they add real value.
- Do not create busywork or overcomplicate simple requests.
- Distinguish between optional improvements and things required for correctness.
- Never claim a change has been made until the autonomous job has actually completed.
- Prefer safe, reversible and observable changes.
- Preserve the LifeOS privacy boundary. This conversational analysis is local. The final engineering job may use cloud Codex, so do not put secrets, private documents, emails, banking, medical data, credentials, tokens or other private content into proposed_job.
- If the request contains private material, produce a safe redacted engineering brief or say that the requested job must remain local-only.

Return JSON only with these keys:
reply: natural conversational response to the user, concise but useful.
understanding: one sentence describing the desired outcome.
needs_clarification: boolean.
clarifying_question: string or empty string.
improvements: array of short strings, maximum 4.
ready_to_run: boolean. True only when the engineering intent is sufficiently clear.
proposed_job: a complete self-contained engineering brief suitable for the LifeOS autonomous agent, or empty string when not ready.
"""


def post_json(url, payload, timeout=180):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def analyse(messages):
    history = []
    for item in messages[-12:]:
        role = str(item.get("role", "user"))[:16]
        content = str(item.get("content", ""))[:6000]
        history.append(f"{role.upper()}: {content}")
    prompt = SYSTEM + "\n\nConversation:\n" + "\n".join(history) + "\n\nReturn the JSON now."
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.25, "num_ctx": 8192},
    }
    result = post_json(OLLAMA_URL, payload)
    raw = result.get("response", "{}")
    parsed = json.loads(raw)
    return {
        "reply": str(parsed.get("reply", "")),
        "understanding": str(parsed.get("understanding", "")),
        "needs_clarification": bool(parsed.get("needs_clarification", False)),
        "clarifying_question": str(parsed.get("clarifying_question", "")),
        "improvements": [str(x) for x in parsed.get("improvements", [])[:4]],
        "ready_to_run": bool(parsed.get("ready_to_run", False)),
        "proposed_job": str(parsed.get("proposed_job", "")),
    }


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, payload):
        self.send_bytes(code, json.dumps(payload, sort_keys=True).encode(), "application/json")

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/assistant"):
            try:
                self.send_bytes(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
            except Exception as exc:
                self.send_json(503, {"error": "ui_unavailable", "detail": type(exc).__name__})
            return
        if self.path == "/health":
            try:
                agent = get_json(AGENT_URL + "/health")
                self.send_json(200, {"service": "lifeos-assistant", "status": "ok", "agent": agent.get("status"), "model": OLLAMA_MODEL})
            except Exception as exc:
                self.send_json(503, {"service": "lifeos-assistant", "status": "degraded", "detail": type(exc).__name__})
            return
        if self.path == "/jobs":
            try:
                self.send_json(200, get_json(AGENT_URL + "/jobs"))
            except Exception as exc:
                self.send_json(502, {"error": "agent_unavailable", "detail": type(exc).__name__})
            return
        if self.path.startswith("/jobs/"):
            try:
                self.send_json(200, get_json(AGENT_URL + self.path))
            except Exception as exc:
                self.send_json(502, {"error": "agent_unavailable", "detail": type(exc).__name__})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/assist":
            try:
                body = self.read_json()
                messages = body.get("messages", [])
                if not isinstance(messages, list) or not messages:
                    self.send_json(400, {"error": "messages_required"})
                    return
                self.send_json(200, analyse(messages))
            except Exception as exc:
                self.send_json(502, {"error": "assistant_unavailable", "detail": type(exc).__name__})
            return
        if self.path == "/run":
            try:
                body = self.read_json()
                request = str(body.get("request", "")).strip()
                if not request:
                    self.send_json(400, {"error": "request_required"})
                    return
                result = post_json(AGENT_URL + "/jobs?async=1", {"request": request}, timeout=15)
                self.send_json(202, result)
            except Exception as exc:
                self.send_json(502, {"error": "agent_unavailable", "detail": type(exc).__name__})
            return
        self.send_json(404, {"error": "not_found"})

    def log_message(self, fmt, *args):
        print("assistant", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"lifeos-assistant listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
