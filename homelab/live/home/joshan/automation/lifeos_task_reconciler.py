#!/usr/bin/env python3
"""LifeOS personal task reconciler.

Reads recent Gmail locally, extracts user obligations with governed local AI, and
reconciles them against Paperless evidence. Private content never leaves the host.
The published HA JSON contains only user-facing task summaries plus stable provenance.
"""
from __future__ import annotations
import email, errno, hashlib, imaplib, json, os, re, socket, ssl, subprocess, sys, time
from email.utils import parsedate_to_datetime
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
import http.client
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO=Path(os.getenv("LIFEOS_PLATFORM_REPO","/home/joshan/lifeos-platform"))
sys.path.insert(0,str(REPO))
from governor import ai_broker
from lifeos_email_paperless_selective import secret, paperless_token
from governor.pa_user_state import apply_user_state, daily_briefing, derive_attention, read_user_state

HA=Path("/opt/stacks/homeassistant/config")
STATE=Path("/home/joshan/automation/state/lifeos_personal_tasks.json")
SCAN_STATE=Path("/home/joshan/automation/state/lifeos_personal_task_scan.json")
OUT=HA/"www/lifeos_tasks.json"
MAX_MESSAGES=int(os.getenv("LIFEOS_TASK_EMAIL_LIMIT","6"))
TASK_CLASSIFICATION_SCHEMA={
    "type":"object",
    "properties":{
        "relevant":{"type":"boolean"},
        "actionable":{"type":"boolean"},
        "title":{"type":"string"},
        "status":{"type":"string","enum":["OPEN","WAITING","DONE","NONE"]},
        "due_date":{"type":["string","null"]},
        "counterparty":{"type":["string","null"]},
        "topic":{"type":"string"},
        "severity":{"type":"string","enum":["LOW","NORMAL","HIGH"]},
        "evidence_query":{"type":"string"},
        "reason":{"type":"string"}
    },
    "required":["relevant","actionable","title","status","due_date","counterparty","topic","severity","evidence_query","reason"],
    "additionalProperties":False
}
LOOKBACK_DAYS=int(os.getenv("LIFEOS_TASK_LOOKBACK_DAYS","90"))
STALE_DAYS=int(os.getenv("LIFEOS_TASK_STALE_DAYS","180"))

def parse_json(raw):
    s=str(raw).strip()
    try:return json.loads(s)
    except Exception:
        a,b=s.find("{"),s.rfind("}")
        if a>=0 and b>a:return json.loads(s[a:b+1])
        raise

def text_of(msg):
    chunks=[]
    for p in msg.walk():
        if p.get_content_maintype()=="text" and not p.get_filename():
            try: chunks.append((p.get_payload(decode=True) or b"").decode(p.get_content_charset() or "utf-8","replace"))
            except Exception: pass
    return "\n".join(chunks)[:12000]

def classify(compact):
    prompt="""You are LifeOS local personal-administration task extraction. Decide whether this email creates, updates, or completes something the user must track. Ignore marketing, newsletters, OTPs, FYI-only mail and ordinary parcel tracking. Return JSON only:
{"relevant":true|false,"actionable":true|false,"title":"short task or event","status":"OPEN|WAITING|DONE|NONE","due_date":"YYYY-MM-DD or null","counterparty":"short name or null","topic":"stable short matter topic","severity":"LOW|NORMAL|HIGH","evidence_query":"terms useful for Paperless search","reason":"short"}
Mark relevant=true for a meaningful update to an existing matter, including informational updates that do not create an obligation. Mark relevant=false for junk, marketing, newsletters, OTPs, generic FYI and ordinary parcel tracking. Do not create obligations from informative events. Do not invent dates or completion. A request, deadline, renewal, claim, appointment preparation, payment/action required, application/process awaiting another party, or explicit resolution may be trackable. Use DONE only when the email itself clearly resolves the tracked matter.
EMAIL:
"""+json.dumps(compact,ensure_ascii=False)
    d=parse_json(ai_broker._ollama(prompt,ai_broker.OLLAMA_MODEL,response_format=TASK_CLASSIFICATION_SCHEMA))
    if not isinstance(d,dict) or not isinstance(d.get("actionable"),bool): raise ValueError("invalid schema")
    if "relevant" not in d:d["relevant"]=bool(d["actionable"])
    if not isinstance(d.get("relevant"),bool): raise ValueError("invalid relevance")
    if str(d.get("status")) not in {"OPEN","WAITING","DONE","NONE"}: raise ValueError("invalid status")
    severity=str(d.get("severity","normal")).lower()
    d["severity"]=severity if severity in {"low","normal","high"} else "normal"
    return d

def paperless_search(query):
    q=" ".join(re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}",str(query)))[:160]
    if not q:return []
    headers={"Authorization":"Token "+paperless_token(),"Accept":"application/json; version=10"}
    req=Request("http://127.0.0.1:8010/api/documents/?"+urlencode({"query":q,"page_size":10}),headers=headers)
    with urlopen(req,timeout=30) as r:d=json.loads(r.read().decode())
    rows=d if isinstance(d,list) else d.get("results",[])
    return [{"document_id":x.get("id"),"title":x.get("title"),"created":x.get("created")} for x in rows[:10]]

def key(d):
    return re.sub(r"[^a-z0-9]+","-",((d.get("counterparty") or "")+" "+(d.get("topic") or d.get("title") or "")).lower()).strip("-")[:120]

def reference_ids(msg):
    values=[str(msg.get("in_reply_to","")),str(msg.get("references",""))]
    return set(re.findall(r"<[^<>]+>", " ".join(values)))

def normalize_counterparty(value):
    return re.sub(r"[^a-z0-9]+","",str(value or "").lower())

def case_reference_ids(msg):
    """Extract only explicitly labelled case/reference identifiers from a message."""
    text=" ".join(str(msg.get(field,"")) for field in ("subject","body"))
    pattern=r"\b(?:case(?:\s*(?:id|no\.?|number|ref(?:erence)?))?|claim(?:\s*(?:id|no\.?|number|ref(?:erence)?))?|reference|ref)\s*(?:(?:is|number)\s*)?[:#=-]?\s*([A-Z0-9][A-Z0-9/_-]{2,39})\b"
    values=set()
    for match in re.finditer(pattern,text,re.IGNORECASE):
        normalized=re.sub(r"[^A-Z0-9]","",match.group(1).upper())
        if 4<=len(normalized)<=40 and any(ch.isdigit() for ch in normalized):
            values.add(normalized)
    return values

def record_source_event(task,msg,decision,observed,actionable=True):
    message_id=str(msg.get("message_id") or msg.get("source_ref") or "")[:300]
    source_ids=set(task.get("source_message_ids") or [])
    if message_id:source_ids.add(message_id)
    if task.get("email_message_id"):source_ids.add(str(task["email_message_id"])[:300])
    task["source_message_ids"]=sorted(source_ids)
    task["case_reference_ids"]=sorted(set(task.get("case_reference_ids") or []) | case_reference_ids(msg))
    events=list(task.get("timeline_events") or [])
    if message_id and not any(str(event.get("message_id") or "")==message_id for event in events if isinstance(event,dict)):
        events.append({
            "message_id":message_id,
            "observed_at":int(observed),
            "date":str(msg.get("date") or "")[:100],
            "title":str(decision.get("title") or "Email update")[:120],
            "status":str(decision.get("status") or "NONE")[:16],
            "event_kind":"obligation" if actionable else "information",
        })
    events.sort(key=lambda event:(int(event.get("observed_at") or 0),str(event.get("message_id") or "")))
    task["timeline_events"]=events[-20:]

def reconcile_information_event(tasks,task_id,msg,decision,observed):
    """Append evidence to a matched matter without creating or mutating its obligation."""
    task=tasks.get(task_id)
    if not isinstance(task,dict):
        return False
    record_source_event(task,msg,decision,observed,actionable=False)
    return True


def thread_root(msg):
    refs=re.findall(r"<[^<>]+>",str(msg.get("references","")))
    if refs:return refs[0]
    replies=re.findall(r"<[^<>]+>",str(msg.get("in_reply_to","")))
    return replies[0] if replies else (str(msg.get("message_id") or msg.get("source_ref") or "")[:300])

def resolve_task_id(d,msg,tasks):
    semantic=key(d)
    refs=reference_ids(msg)
    case_refs=case_reference_ids(msg)
    counterparty=normalize_counterparty(d.get("counterparty"))
    topic=re.sub(r"[^a-z0-9]+"," ",str(d.get("topic") or "").lower()).strip()
    ref_matches=[]
    case_matches=[]
    topic_matches=[]
    legacy_matches=[]
    for task_id,task in tasks.items():
        known=set(task.get("source_message_ids") or [])
        if task.get("email_message_id"):known.add(str(task["email_message_id"]))
        if refs & known:ref_matches.append((task_id,task))
        task_refs=set(task.get("case_reference_ids") or [])
        if case_refs and case_refs & task_refs:
            case_matches.append((task_id,task))
        task_counterparty=normalize_counterparty(task.get("counterparty"))
        task_topic=re.sub(r"[^a-z0-9]+"," ",str(task.get("topic") or "").lower()).strip()
        # A stable labelled case reference is strong identity evidence even
        # when sender-derived counterparty labels differ across messages.
        # Without one, only a unique exact counterparty + topic match may join
        # separate threads. Conflicting or one-sided case references block it.
        references_compatible=(
            not case_refs and not task_refs
        ) or bool(case_refs & task_refs)
        if counterparty and task_counterparty==counterparty and topic and task_topic==topic and references_compatible:
            topic_matches.append((task_id,task))
        same_legacy_message=str(task.get("email_message_id") or "")==str(msg.get("message_id") or "")
        has_no_source_ref=not task.get("email_message_id") and not task.get("source_message_ids")
        if not task.get("thread_root_id") and task.get("identity_semantic",task_id)==semantic and (same_legacy_message or has_no_source_ref):
            legacy_matches.append((task_id,task))
    semantic_ref_matches=[x for x in ref_matches if x[1].get("identity_semantic")==semantic]
    if len(semantic_ref_matches)==1:return semantic_ref_matches[0][0]
    if len(ref_matches)==1:return ref_matches[0][0]
    if len(case_matches)==1:return case_matches[0][0]
    if len(topic_matches)==1:return topic_matches[0][0]
    if len(legacy_matches)==1:return legacy_matches[0][0]
    root=thread_root(msg)
    if not semantic or not root:return ""
    digest=hashlib.sha256(root.encode("utf-8","replace")).hexdigest()[:12]
    return semantic[:80]+"-"+digest

def observation_is_newer(old,observed):
    try:return int(observed)>=int(old.get("observed_at") or 0)
    except Exception:return True

def effective_status(old,new_status):
    if old.get("status")=="DONE" and new_status!="DONE":return "DONE"
    return new_status

def load_previous():
    try:
        data=json.loads(STATE.read_text())
        rows=(data.get("tasks") or [])+(data.get("resolved") or [])
        previous={}
        for x in rows:
            if not isinstance(x,dict) or not x.get("id"): continue
            item=dict(x)
            if str(item.get("machine_status") or "").upper() in {"OPEN","WAITING","DONE","DISMISSED"}:
                item["status"]=item["machine_status"]
            item.pop("status_source",None); item.pop("status_set_at",None)
            item.pop("severity_source",None); item.pop("due_date_source",None)
            previous[str(item["id"])]=item
        return previous
    except Exception:return {}

def load_scan_state():
    try:
        data=json.loads(SCAN_STATE.read_text())
        return data if data.get("schema")=="lifeos_task_scan_v1" else {}
    except Exception:return {}

def message_time(date_value):
    try:return int(parsedate_to_datetime(str(date_value or "")).timestamp())
    except Exception:return int(time.time())


_FAILURE_STAGES = frozenset({
    "startup", "state_load", "credential_load", "mailbox_connect",
    "mailbox_search", "mailbox_fetch", "classification", "paperless_lookup",
    "reconcile", "persist_publish", "complete",
})
_FAILURE_STAGE = "startup"


def set_failure_stage(stage):
    """Set a fixed diagnostic stage; never retain arbitrary caller text."""
    global _FAILURE_STAGE
    _FAILURE_STAGE = stage if stage in _FAILURE_STAGES else "startup"


def safe_error_bucket(exc):
    """Map exceptions to fixed labels without inspecting messages or reprs."""
    if isinstance(exc, ssl.SSLError):
        return "TLS"
    if isinstance(exc, imaplib.IMAP4.error):
        return "IMAP"
    if isinstance(exc, (HTTPError, http.client.HTTPException)):
        return "HTTP"
    if isinstance(exc, URLError):
        return "NETWORK"
    if isinstance(exc, json.JSONDecodeError):
        return "JSON"
    if isinstance(exc, (socket.timeout, socket.gaierror, socket.herror, TimeoutError, ConnectionError)):
        return "NETWORK"
    if isinstance(exc, (FileNotFoundError, PermissionError)):
        return "FILESYSTEM"
    if isinstance(exc, OSError):
        if exc.errno in {
            errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
            errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ETIMEDOUT, errno.EPIPE,
        }:
            return "NETWORK"
        return "IO"
    if isinstance(exc, (ValueError, TypeError, KeyError, AssertionError)):
        return "DATA"
    return "OTHER"


def safe_failure_diagnostic(exc, stage=None):
    """Return fixed-format markers; never include exception text."""
    stage = stage if stage in _FAILURE_STAGES else _FAILURE_STAGE
    return (
        f"TASK_RECONCILER_FAILURE_STAGE={stage}\n"
        f"TASK_RECONCILER_FAILURE_BUCKET={safe_error_bucket(exc)}"
    )

def safe_classification_error_category(exc):
    """Emit only a fixed category; never expose model, message, or document content."""
    if isinstance(exc, ai_broker.BrokerError):
        message = str(exc)
        match = re.match(r"^provider HTTP ([1-5][0-9][0-9]):", message)
        if match:
            return "UPSTREAM_HTTP_" + match.group(1)
        if message.startswith("provider request failed:"):
            return "PROVIDER_REQUEST_FAILED"
        if message == "ollama returned empty response":
            return "EMPTY_RESPONSE"
        if message.startswith("Tower compute lease unavailable:"):
            return "COMPUTE_LEASE"
        if message.startswith("eligible providers exhausted:"):
            return "PROVIDER_EXHAUSTED"
        return "BROKER_OTHER"
    if isinstance(exc, json.JSONDecodeError):
        return "JSON_RESPONSE"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "TIMEOUT"
    return "OTHER"



JUNK_REQUESTS = Path("/opt/stacks/homeassistant/config/lifeos-pa-state/junk-requests")
JUNK_FAILED = JUNK_REQUESTS / "failed"


def _paperless_document(document_id):
    headers = {"Authorization": "Token " + paperless_token(), "Accept": "application/json; version=10"}
    request = Request("http://127.0.0.1:8010/api/documents/" + str(document_id) + "/", headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _paperless_delete(document_id):
    headers = {"Authorization": "Token " + paperless_token(), "Accept": "application/json; version=10"}
    request = Request("http://127.0.0.1:8010/api/documents/" + str(document_id) + "/", method="DELETE", headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
    except HTTPError as exc:
        if exc.code != 404:
            raise
    if _paperless_document(document_id) is not None:
        raise RuntimeError("paperless_delete_unverified")


def _junk_message_ids(task):
    values = set(str(x) for x in (task.get("source_message_ids") or []) if x)
    if task.get("email_message_id"):
        values.add(str(task["email_message_id"]))
    if not values or len(values) > 20:
        raise ValueError("source_email_set_invalid")
    for value in values:
        if (len(value) > 300 or not value.startswith("<") or not value.endswith(">")
                or any(ord(ch) < 32 or ch in (chr(34), chr(92)) for ch in value)):
            raise ValueError("source_email_id_invalid")
    return sorted(values)


def _mark_imap_message_as_spam(client, uid):
    status, _ = client.uid("STORE", uid, "+X-GM-LABELS", r"(\Spam)")
    if status != "OK":
        raise RuntimeError("imap_spam_label_failed")
    status, _ = client.uid("STORE", uid, "-X-GM-LABELS", r"(\Inbox)")
    if status != "OK":
        raise RuntimeError("imap_inbox_label_remove_failed")


def _move_emails_to_junk(message_ids):
    user = secret("LIFEOS_IMAP_USER", ("gmail-imap-user", "imap-user", "gmail-user"))
    password = secret("LIFEOS_IMAP_PASSWORD", ("gmail-imap-password", "imap-password", "gmail-app-password"))
    client = imaplib.IMAP4_SSL(
        os.getenv("LIFEOS_IMAP_HOST", "imap.gmail.com"),
        int(os.getenv("LIFEOS_IMAP_PORT", "993")),
        ssl_context=ssl.create_default_context(),
    )
    try:
        client.login(user, password)
        capabilities = {x.upper() for x in client.capabilities}
        if b"X-GM-EXT-1" not in capabilities:
            raise RuntimeError("imap_gmail_labels_unsupported")
        folders = {}
        status, boxes = client.list()
        if status == "OK":
            for row in boxes or []:
                parts = row.split(b'"')
                if len(parts) < 3:
                    continue
                candidate = parts[-2].decode("ascii", "strict")
                if candidate not in {"[Gmail]/Spam", "[GoogleMail]/Spam", "[Gmail]/All Mail", "[GoogleMail]/All Mail"}:
                    continue
                if bytes((92,)) + b"JUNK" in row.upper():
                    folders["junk"] = candidate
                if bytes((92,)) + b"ALL" in row.upper():
                    folders["all"] = candidate
        junk_box = folders.get("junk")
        all_box = folders.get("all")
        if not junk_box:
            raise RuntimeError("imap_junk_folder_unavailable")
        status, _ = client.select("INBOX", readonly=False)
        if status != "OK":
            raise RuntimeError("imap_inbox_unavailable")
        inbox_matches = {}
        for message_id in message_ids:
            status, rows = client.uid("search", None, "HEADER", "Message-ID", message_id)
            matches = rows[0].split() if status == "OK" and rows else []
            if len(matches) > 1:
                raise RuntimeError("imap_message_ambiguous")
            inbox_matches[message_id] = matches[0] if matches else None
        status, _ = client.select(junk_box, readonly=True)
        if status != "OK":
            raise RuntimeError("imap_junk_folder_unavailable")
        pending = {}
        for message_id, inbox_uid in inbox_matches.items():
            status, rows = client.uid("search", None, "HEADER", "Message-ID", message_id)
            matches = rows[0].split() if status == "OK" and rows else []
            if len(matches) > 1 or (inbox_uid is not None and matches):
                raise RuntimeError("imap_message_ambiguous")
            if inbox_uid is not None:
                pending[message_id] = ("INBOX", inbox_uid)
            elif matches:
                pending[message_id] = (None, None)
            else:
                pending[message_id] = ("", None)
        missing = [message_id for message_id, (box, uid) in pending.items() if box == ""]
        if missing:
            if not all_box:
                raise RuntimeError("imap_all_mail_folder_unavailable")
            status, _ = client.select(all_box, readonly=True)
            if status != "OK":
                raise RuntimeError("imap_all_mail_folder_unavailable")
            for message_id in missing:
                status, rows = client.uid("search", None, "HEADER", "Message-ID", message_id)
                matches = rows[0].split() if status == "OK" and rows else []
                if len(matches) != 1:
                    raise RuntimeError("imap_message_not_found")
                pending[message_id] = (all_box, matches[0])
        for message_id, (source_box, uid) in pending.items():
            if source_box is None:
                continue
            status, _ = client.select(source_box, readonly=False)
            if status != "OK":
                raise RuntimeError("imap_source_folder_unavailable")
            _mark_imap_message_as_spam(client, uid)
        status, _ = client.select(junk_box, readonly=True)
        if status != "OK":
            raise RuntimeError("imap_junk_folder_unavailable")
        for message_id in message_ids:
            status, rows = client.uid("search", None, "HEADER", "Message-ID", message_id)
            if status != "OK" or not rows or len(rows[0].split()) != 1:
                raise RuntimeError("imap_spam_unverified")
            spam_uid = rows[0].split()[0]
            status, rows = client.uid("fetch", spam_uid, "(X-GM-LABELS)")
            if status != "OK" or not rows:
                raise RuntimeError("imap_spam_unverified")
            label_data = b" ".join(row for row in rows if isinstance(row, bytes)).upper()
            if b"\\SPAM" not in label_data or b"\\INBOX" in label_data:
                raise RuntimeError("imap_spam_unverified")
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _process_junk_request(path):
    request = json.loads(path.read_text(encoding="utf-8"))
    if request.get("schema") != "lifeos_pa_junk_request_v1":
        raise ValueError("junk_request_schema_invalid")
    task_id = str(request.get("task_id") or "")
    request_id = str(request.get("request_id") or "")
    document_ids = request.get("paperless_document_ids")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", task_id):
        raise ValueError("junk_task_id_invalid")
    if path.name != task_id + ".json" or not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("junk_request_identity_invalid")
    if (not isinstance(document_ids, list) or not document_ids or len(document_ids) > 5
            or any(not isinstance(x, int) or x <= 0 for x in document_ids)
            or len(set(document_ids)) != len(document_ids)):
        raise ValueError("paperless_selection_invalid")
    previous = load_previous()
    task = previous.get(task_id)
    if not task:
        raise ValueError("junk_task_unavailable")
    if str(task.get("status") or "").upper() not in {"OPEN", "WAITING"}:
        raise ValueError("junk_task_not_open")
    linked = {
        int(doc["document_id"])
        for doc in (task.get("paperless_evidence") or [])
        if isinstance(doc, dict) and str(doc.get("document_id") or "").isdigit()
    }
    if not set(document_ids).issubset(linked):
        raise ValueError("paperless_selection_not_linked")
    message_ids = _junk_message_ids(task)
    # Validate every Paperless target before moving any source email.
    for document_id in document_ids:
        _paperless_document(document_id)
    _move_emails_to_junk(message_ids)
    for document_id in document_ids:
        _paperless_delete(document_id)
    result = subprocess.run(
        ["docker", "exec", "homeassistant", "python3",
         "/config/scripts/lifeos_pa_user_action.py", "--action", "dismiss", "--task-id", task_id],
        check=True, capture_output=True, text=True, timeout=30,
    )
    if "PA_USER_ACTION=PASS" not in result.stdout:
        raise RuntimeError("junk_task_dismiss_unverified")


def process_junk_requests():
    if not JUNK_REQUESTS.is_dir():
        return
    JUNK_FAILED.mkdir(mode=0o700, exist_ok=True)
    for path in sorted(JUNK_REQUESTS.glob("*.json")):
        try:
            _process_junk_request(path)
            path.unlink()
            stale_failure = JUNK_FAILED / path.name
            if stale_failure.exists():
                stale_failure.unlink()
            print("PA_JUNK_ACTION=PASS", flush=True)
        except Exception as exc:
            try:
                path.replace(JUNK_FAILED / path.name)
            except Exception:
                pass
            print("PA_JUNK_ACTION=FAIL", flush=True)
            print("PA_JUNK_ACTION_ERROR=" + type(exc).__name__, flush=True)



def _run_reconciler():
    set_failure_stage("state_load")
    previous=load_previous()
    scan=load_scan_state()
    set_failure_stage("credential_load")
    user=secret("LIFEOS_IMAP_USER",("gmail-imap-user","imap-user","gmail-user"))
    password=secret("LIFEOS_IMAP_PASSWORD",("gmail-imap-password","imap-password","gmail-app-password"))
    set_failure_stage("mailbox_connect")
    c=imaplib.IMAP4_SSL(os.getenv("LIFEOS_IMAP_HOST","imap.gmail.com"),int(os.getenv("LIFEOS_IMAP_PORT","993")),ssl_context=ssl.create_default_context())
    c.login(user,password);c.select("INBOX",readonly=True)
    try:
        _,validity_rows=c.response("UIDVALIDITY")
        uidvalidity=(validity_rows or [b""])[0].decode(errors="ignore")
    except Exception:
        uidvalidity=""
    if scan.get("uidvalidity")!=uidvalidity:
        scan={}
    set_failure_stage("mailbox_search")
    status,rows=c.uid("search",None,"SINCE",time.strftime("%d-%b-%Y",time.localtime(time.time()-LOOKBACK_DAYS*86400)))
    all_ids=sorted({int(x) for x in (rows[0].split() if status=="OK" and rows else [])})
    cursor=int(scan.get("before_uid") or 0)
    candidates=[x for x in all_ids if not cursor or x<cursor]
    if not candidates:
        candidates=all_ids
    ids=candidates[-MAX_MESSAGES:]
    next_cursor=ids[0] if ids else 0
    set_failure_stage("mailbox_fetch")
    fetched=[];errors=0;fetch_errors=0;fetch_error_types=set()
    for uid in ids:
        try:
            st,data=c.uid("fetch",str(uid),"(RFC822)")
            if st!="OK":continue
            raw=next(x[1] for x in data if isinstance(x,tuple));msg=email.message_from_bytes(raw)
            message_id=str(msg.get("Message-ID",""))[:300]
            fetched.append({
                "from":str(msg.get("From",""))[:300],
                "subject":str(msg.get("Subject",""))[:500],
                "date":str(msg.get("Date",""))[:100],
                "message_id":message_id,
                "in_reply_to":str(msg.get("In-Reply-To",""))[:500],
                "references":str(msg.get("References",""))[:2000],
                "source_ref":message_id or (uidvalidity+":"+str(uid)),
                "body":text_of(msg),
            })
        except Exception as exc:
            errors+=1;fetch_errors+=1;fetch_error_types.add(type(exc).__name__)
    try:
        c.logout()
    except Exception:
        pass

    # Keep the network mailbox session out of the slow local inference loop.
    processed_order=list(scan.get("processed_message_ids") or [])
    processed=set(processed_order)
    new_fetched=[]
    messages_reused=0
    for compact in fetched:
        if compact["source_ref"] in processed:
            messages_reused+=1
        else:
            new_fetched.append(compact)
    print("TASK_SCAN_FETCHED="+str(len(fetched)),flush=True)
    set_failure_stage("classification")
    observations=[]
    classification_attempts=0;classification_errors=0;classification_error_types=set();classification_error_categories={}
    for index,compact in enumerate(new_fetched,1):
        print("TASK_CLASSIFICATION_PROGRESS="+str(index)+"/"+str(len(new_fetched)),flush=True)
        try:
            classification_attempts+=1
            d=classify(compact)
            processed.add(compact["source_ref"])
            processed_order.append(compact["source_ref"])
            if not d["relevant"] or (d["actionable"] and d["status"]=="NONE"):continue
            k=key(d)
            if not k:continue
            observations.append((message_time(compact.get("date")),k,d,compact))
        except Exception as exc:
            errors+=1;classification_errors+=1;classification_error_types.add(type(exc).__name__)
            category=safe_classification_error_category(exc)
            classification_error_categories[category]=classification_error_categories.get(category,0)+1
    # Reconcile chronologically so a later completion/update wins over an older
    # request. Preserve prior state when a task is outside this bounded scan.
    set_failure_stage("reconcile")
    tasks=dict(previous)
    for observed,k,d,msg in sorted(observations,key=lambda x:x[0]):
        task_id=resolve_task_id(d,msg,tasks)
        if not task_id:continue
        old=tasks.get(task_id,{})
        if not d["actionable"]:
            reconcile_information_event(tasks,task_id,msg,d,observed)
            continue
        if old:
            record_source_event(old,msg,d,observed)
        if old and not observation_is_newer(old,observed):
            tasks[task_id]=old
            continue
        source_ids=set(old.get("source_message_ids") or [])
        if msg.get("message_id"):source_ids.add(str(msg["message_id"])[:300])
        status=effective_status(old,d["status"])
        set_failure_stage("paperless_lookup")
        evidence=paperless_search(d.get("evidence_query") or d.get("topic") or d.get("title"))
        tasks[task_id]={
            "id":task_id,"identity_semantic":key(d),"thread_root_id":thread_root(msg),
            "title":str(d.get("title") or old.get("title") or "Untitled task")[:160],
            "status":status,"due_date":d.get("due_date") or old.get("due_date"),
            "counterparty":d.get("counterparty") or old.get("counterparty"),
            "topic":d.get("topic") or old.get("topic"),"severity":d.get("severity") or old.get("severity") or "normal","source":"gmail",
            "email_message_id":str(msg.get("message_id",""))[:300],
            "source_message_ids":sorted(source_ids),
            "case_reference_ids":sorted(set(old.get("case_reference_ids") or []) | case_reference_ids(msg)),
            "timeline_events":list(old.get("timeline_events") or []),
            "paperless_evidence":evidence or old.get("paperless_evidence",[]),
            "updated_from_email":str(msg.get("date",""))[:100],"observed_at":observed,
            "reason":str(d.get("reason") or "")[:300]
        }
        record_source_event(tasks[task_id],msg,d,observed)
    cutoff=int(time.time())-STALE_DAYS*86400
    tasks={k:v for k,v in tasks.items() if int(v.get("observed_at") or int(time.time()))>=cutoff or v.get("status")!="DONE"}
    open_tasks=[x for x in tasks.values() if x.get("status")!="DONE"]
    resolved=[x for x in tasks.values() if x.get("status")=="DONE"]
    open_tasks.sort(key=lambda x:(x.get("due_date") or "9999-99-99",x["title"]))
    payload={"schema":"lifeos_tasks_v3","generated_time":int(time.time()),"lookback_days":LOOKBACK_DAYS,"messages_considered":len(ids),"messages_classified":classification_attempts,"messages_reused":messages_reused,"errors":errors,"tasks":open_tasks,"resolved":resolved,"authority":{"email":"obligation/progress evidence","paperless":"document evidence","lifeos":"derived persistent task state"}}
    payload=apply_user_state(payload,read_user_state())
    set_failure_stage("persist_publish")
    STATE.parent.mkdir(parents=True,exist_ok=True);OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(payload,indent=2)+"\n");tmp.replace(STATE)
    outtmp=OUT.with_suffix(".tmp");outtmp.write_text(json.dumps(payload,indent=2)+"\n");outtmp.replace(OUT)
    scan_payload={"schema":"lifeos_task_scan_v1","uidvalidity":uidvalidity,"before_uid":next_cursor,"processed_message_ids":processed_order[-10000:],"updated_time":int(time.time())}
    scan_tmp=SCAN_STATE.with_suffix(".tmp");scan_tmp.write_text(json.dumps(scan_payload,indent=2)+"\n");scan_tmp.replace(SCAN_STATE)
    print('TASK_FETCH_ERRORS='+str(fetch_errors),flush=True)
    print('TASK_FETCH_ERROR_TYPES='+(','.join(sorted(fetch_error_types)) or 'NONE'),flush=True)
    print('TASK_CLASSIFICATION_ERRORS='+str(classification_errors),flush=True)
    print('TASK_CLASSIFICATION_ERROR_TYPES='+(','.join(sorted(classification_error_types)) or 'NONE'),flush=True)
    print('TASK_CLASSIFICATION_ERROR_CATEGORIES='+(','.join(f"{k}={v}" for k,v in sorted(classification_error_categories.items())) or 'NONE'),flush=True)
    set_failure_stage("complete")
    print(json.dumps({"tasks":len(open_tasks),"resolved":len(resolved),"messages":len(ids),"classified":classification_attempts,"reused":messages_reused,"errors":errors}))

def main():
    set_failure_stage("startup")
    try:
        _run_reconciler()
    except Exception as exc:
        print(safe_failure_diagnostic(exc), flush=True)
        raise SystemExit(1)

if __name__=="__main__":main()
