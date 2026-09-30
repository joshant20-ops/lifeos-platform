#!/usr/bin/env python3
import hmac
import json
import os
import pathlib
import stat
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ai_broker import BrokerError, generate
import re

PRIVACY_DOMAIN_POLICY_PATH = pathlib.Path(os.environ.get("LIFEOS_PRIVACY_DOMAIN_POLICY", pathlib.Path(__file__).with_name("privacy-domain-policy.json")))
PRIVATE_PATTERNS = (
    r"\\bpaperless\\b", r"\\bprivate (?:data|documents?|files?|records?|information)\\b",
    r"\\bpersonal (?:data|documents?|files?|records?|information)\\b",
    r"\\bmedical (?:data|records?|documents?|information)\\b", r"\\bhealth (?:data|records?|documents?|information)\\b",
    r"\\bpassport(?:s)?\\b", r"\\bbank (?:accounts?|statements?|details|records?|documents?)\\b",
    r"\\bfinancial (?:statements?|records?|data|documents?)\\b", r"\\bpersonal (?:invoice|invoices|email|emails|mailbox|inbox)\\b",
    r"\\b(?:email|emails|mailbox|inbox)\\b.{0,40}\\b(?:private|personal|messages?|content)\\b",
)

def _privacy_domain_policy():
    try:
        policy=json.loads(PRIVACY_DOMAIN_POLICY_PATH.read_text())
        if policy.get("schema_version") != 1 or policy.get("fail_closed") is not True or not isinstance(policy.get("domains"), dict): return None
        return policy
    except Exception: return None

def _privacy_term_matches(lower, term):
    normalized=re.escape(str(term).strip().lower()).replace(r"\\ ", r"[\\s_-]+").replace(r"\\-", r"[\\s_-]+")
    return bool(normalized and re.search(rf"(?<!\\w){normalized}(?!\\w)", lower))

def classify_privacy(text, domain=None):
    lower=str(text or "").lower()
    if any(re.search(pattern, lower) for pattern in PRIVATE_PATTERNS): return "local-only"
    policy=_privacy_domain_policy()
    if policy is None: return "local-only"
    domains=policy["domains"]
    if domain:
        key=re.sub(r"[\\s_]+", "-", str(domain).strip().lower()); rule=domains.get(key)
        if not isinstance(rule, dict): return "local-only"
        return "local-only" if rule.get("privacy") == "local-only" else str(policy.get("default") or "normal")
    for rule in domains.values():
        if isinstance(rule, dict) and rule.get("privacy") == "local-only" and any(_privacy_term_matches(lower,t) for t in rule.get("request_terms", ())): return "local-only"
    return str(policy.get("default") or "normal")

PORT = int(os.environ.get("LIFEOS_ASSISTANT_PORT", "8791"))
AGENT_URL = os.environ.get("LIFEOS_AGENT_URL", "http://127.0.0.1:8790")
UI_PATH = pathlib.Path(os.environ.get("LIFEOS_ASSISTANT_UI", "/home/joshan/lifeos-platform/governor/assistant_ui.html"))
PA_TASKS_FILE = pathlib.Path(os.environ.get("LIFEOS_PA_TASKS_FILE", "/opt/stacks/homeassistant/config/www/lifeos_tasks.json"))
BROKER_TOKEN_FILE = pathlib.Path(
    os.environ.get("LIFEOS_AI_BROKER_TOKEN_FILE", pathlib.Path.home() / ".config/lifeos/ai-broker.token")
)

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
- Preserve the LifeOS privacy boundary. Private/personal/financial/document context is local-only.
- Cloud-safe public/general analysis may use Governor-approved cloud inference.
- Do not put secrets, private documents, emails, banking, medical data, credentials, tokens or other private content into proposed_job.
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


def _read_pa_task_state(now_ts=None):
    try:
        payload=json.loads(PA_TASKS_FILE.read_text())
        generated=int(payload.get("generated_time") or 0)
        now_ts=int(now_ts if now_ts is not None else time.time())
        if payload.get("schema")!="lifeos_tasks_v3" or not generated or now_ts-generated>7*3600:
            return None
        return payload
    except Exception:
        return None


def pa_structured_answer(question, payload=None, now_ts=None):
    """Answer supported everyday PA questions from the local derived task view."""
    q=" ".join(str(question or "").lower().split())
    route=None
    query_term=""
    if any(x in q for x in ("what needs me","what needs my attention","what do i need to do","what should i do next")):
        route="needs_me"
    elif any(x in q for x in ("what am i waiting for","what are others doing","waiting on others","what is someone else doing")):
        route="waiting_on_others"
    elif any(x in q for x in ("what changed","what has changed","what changed recently")):
        route="changed"
    elif any(x in q for x in ("due soon","due this week","what is overdue","what's overdue","what is due")):
        route="due"
    else:
        match=re.search(r"\bevidence\b.{0,80}?\b(?:for|about)\s+(.+)$",q)
        if match:
            route="evidence"
            query_term=match.group(1).strip(" ?.!")[:100]
    if not route:
        return None
    payload=payload if payload is not None else _read_pa_task_state(now_ts)
    if not isinstance(payload,dict):
        return {"handled":True,"ok":False,"route":"structured_pa_state","source_schema":"lifeos_tasks_v3","privacy":"local-only","confidence":"unavailable","reply":"The local PA task view is unavailable or stale, so I can't give a current answer."}
    attention=payload.get("attention") if isinstance(payload.get("attention"),dict) else {}
    now_ts=int(now_ts if now_ts is not None else time.time())
    if route=="needs_me":
        items=list(attention.get("needs_me") or [x for x in payload.get("tasks",[]) if x.get("status")=="OPEN"])
        label="Needs me"
    elif route=="waiting_on_others":
        items=list(attention.get("waiting_on_others") or [x for x in payload.get("tasks",[]) if x.get("status")=="WAITING"])
        label="Waiting on others"
    elif route=="due":
        items=list(attention.get("due_overdue") or [])+list(attention.get("upcoming") or [])
        if not items:
            items=[x for x in payload.get("tasks",[]) if x.get("status") in {"OPEN","WAITING"} and x.get("due_date")]
        label="Due soon or overdue"
    elif route=="changed":
        all_items=list(payload.get("tasks",[]))+list(payload.get("resolved",[]))
        items=[x for x in all_items if 0<=now_ts-int(x.get("observed_at") or 0)<=7*86400]
        items.sort(key=lambda x:(-int(x.get("observed_at") or 0),str(x.get("id",""))))
        label="Changed in the last seven days"
    else:
        tokens=[x for x in re.findall(r"[a-z0-9]+",query_term) if len(x)>1]
        all_items=list(payload.get("tasks",[]))+list(payload.get("resolved",[]))
        items=[]
        for task in all_items:
            text=" ".join([str(task.get(k) or "") for k in ("title","topic","counterparty")])
            evidence=task.get("paperless_evidence") or []
            evidence_text=" ".join(str(x.get(k) or "") for x in evidence if isinstance(x,dict) for k in ("title","document_id"))
            haystack=(text+" "+evidence_text).lower()
            if tokens and all(token in haystack for token in tokens):
                items.append(task)
        label="Paperless evidence references"
    unique=[]
    seen=set()
    for item in items:
        if not isinstance(item,dict): continue
        identity=str(item.get("id") or item.get("email_message_id") or item.get("document_id") or "")
        if identity and identity not in seen:
            seen.add(identity)
            unique.append(item)
    if route=="evidence":
        refs=[]
        for task in unique:
            for doc in task.get("paperless_evidence") or []:
                if isinstance(doc,dict):
                    refs.append(f"Paperless #{doc.get('document_id')}: {str(doc.get('title') or 'document reference')[:120]}")
        lines=refs[:5]
        if not lines:
            reply="No linked Paperless evidence reference for that topic is present in the local PA task view. Ask LifeOS can search Paperless directly."
        else:
            reply="Evidence references for "+query_term+":\n- "+"\n- ".join(lines)
    else:
        if not unique:
            reply=f"{label}: none in the current structured PA view."
        else:
            lines=[]
            for item in unique[:5]:
                title=str(item.get("title") or "Untitled task")[:160]
                status=str(item.get("status") or "").lower()
                due=str(item.get("due_date") or "")
                suffix=("; due "+due) if due else ""
                lines.append(f"- {title} ({status}{suffix})")
            reply=f"{label} ({len(unique)} shown):\n"+"\n".join(lines)
    reply+="\n\nSource: local structured PA state. Confidence: structured state only; source references are retained."
    return {"handled":True,"ok":True,"route":"structured_pa_state","source_schema":"lifeos_tasks_v3","privacy":"local-only","confidence":"structured_state_only","matched_view":route,"reply":reply,"result_count":len(unique)}


def post_json(url, payload, timeout=180):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def analyse(messages, privacy_domain=None):
    history = []
    raw_context = []
    last_user = ""
    for item in messages[-12:]:
        role = str(item.get("role", "user"))[:16]
        content = str(item.get("content", ""))[:6000]
        history.append(f"{role.upper()}: {content}")
        raw_context.append(content)
        if role == "user": last_user = content
    structured = pa_structured_answer(last_user)
    if structured:
        return {"reply":structured["reply"],"understanding":"Answer from the local structured PA view.","needs_clarification":False,"clarifying_question":"","improvements":[],"ready_to_run":False,"proposed_job":"","privacy":"local-only","provider":"structured_local_state","route":structured["route"],"source_schema":structured["source_schema"],"confidence":structured["confidence"]}
    # The PA is personal by definition: its conversational context may contain
    # household/personal data even when a particular sentence looks generic.
    # Keep PA inference local-first/fail-closed; only the separately approved
    # engineering brief may cross the sanitized engineering boundary.
    privacy = "local-only"
    prompt = SYSTEM + "\n\nConversation:\n" + "\n".join(history) + "\n\nReturn the JSON now."
    routed = generate(prompt, privacy=privacy, task_class="normal")
    parsed = json.loads(routed["text"])
    return {
        "reply": str(parsed.get("reply", "")),
        "understanding": str(parsed.get("understanding", "")),
        "needs_clarification": bool(parsed.get("needs_clarification", False)),
        "clarifying_question": str(parsed.get("clarifying_question", "")),
        "improvements": [str(x) for x in parsed.get("improvements", [])[:4]],
        "ready_to_run": bool(parsed.get("ready_to_run", False)),
        "proposed_job": str(parsed.get("proposed_job", "")),
        "privacy": privacy,
        "provider": routed["provider"],
    }


def _broker_token():
    try:
        if not BROKER_TOKEN_FILE.is_file() or BROKER_TOKEN_FILE.is_symlink():
            return ""
        if stat.S_IMODE(BROKER_TOKEN_FILE.stat().st_mode) != 0o600:
            return ""
        return BROKER_TOKEN_FILE.read_text().strip()
    except OSError:
        return ""


def _broker_authorized(headers):
    expected = _broker_token()
    supplied = str(headers.get("Authorization", ""))
    return bool(
        expected
        and supplied.startswith("Bearer ")
        and hmac.compare_digest(supplied[7:].encode(), expected.encode())
    )


def broker_chat(body):
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages_required")
    lines = []
    raw = []
    last_user = ""
    for item in messages[-24:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user"))[:16]
        content = item.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
            )
        content = str(content)[:12000]
        lines.append(f"{role.upper()}: {content}")
        raw.append(content)
        if role == "user": last_user=content
    if not lines:
        raise ValueError("messages_required")
    structured = pa_structured_answer(last_user)
    if structured:
        return {
            "id": "chatcmpl-" + uuid.uuid4().hex[:20],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "lifeos-structured-pa",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": structured["reply"]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "lifeos_provider": "structured_local_state",
            "lifeos_privacy": "local-only",
            "lifeos_task_class": "personal-administration",
        }
    requested_model = str(body.get("model", "lifeos-normal"))
    requested_privacy = "local-only" if "local-only" in requested_model else "normal"
    task_class = "normal"
    for candidate in ("substantial", "review", "normal"):
        if candidate in requested_model:
            task_class = candidate
            break
    detected = classify_privacy("\n".join(raw))
    privacy = "local-only" if detected == "local-only" else requested_privacy
    routed = generate("\n".join(lines), privacy=privacy, task_class=task_class)
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:20],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": routed["model"],
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": routed["text"]},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "lifeos_provider": routed["provider"],
        "lifeos_privacy": privacy,
        "lifeos_task_class": task_class,
    }


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
                self.send_json(200, {
                    "service": "lifeos-assistant",
                    "status": "ok",
                    "agent": agent.get("status"),
                    "inference": "governor-routed",
                    "cloud_requires_engineer": False,
                    "broker_api": "/v1/chat/completions",
                })
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
        if self.path == "/v1/chat/completions":
            if not _broker_authorized(self.headers):
                self.send_json(401, {"error": "broker_capability_required"})
                return
            try:
                self.send_json(200, broker_chat(self.read_json()))
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
            except BrokerError as exc:
                self.send_json(503, {"error": "inference_unavailable", "detail": str(exc)})
            except Exception as exc:
                self.send_json(502, {"error": "broker_unavailable", "detail": type(exc).__name__})
            return
        if self.path == "/assist":
            try:
                body = self.read_json()
                messages = body.get("messages", [])
                if not isinstance(messages, list) or not messages:
                    self.send_json(400, {"error": "messages_required"})
                    return
                self.send_json(200, analyse(messages, privacy_domain=body.get("privacy_domain")))
            except BrokerError as exc:
                self.send_json(503, {"error": "inference_unavailable", "detail": str(exc)})
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
                payload = {"request": request}
                if body.get("privacy_domain"):
                    payload["privacy_domain"] = body.get("privacy_domain")
                result = post_json(AGENT_URL + "/jobs?async=1", payload, timeout=15)
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
