#!/usr/bin/env python3
"""LifeOS personal task reconciler.

Reads recent Gmail locally, extracts user obligations with governed local AI, and
reconciles them against Paperless evidence. It also rechecks each saved task's
primary source email so explicit no-action notices can remove false-positive tasks.
Private content never leaves the host. The published HA JSON contains only
user-facing task summaries plus stable provenance.
"""
from __future__ import annotations
import email, errno, hashlib, html, imaplib, json, os, re, socket, ssl, subprocess, sys, time
from email.utils import parsedate_to_datetime, parseaddr
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
import http.client
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO=Path(os.getenv("LIFEOS_PLATFORM_REPO","/home/joshan/lifeos-platform"))
sys.path.insert(0,str(REPO))
from governor import ai_broker
from lifeos_email_paperless_selective import secret, paperless_token
from governor.pa_user_state import apply_user_state, daily_briefing, derive_attention, read_user_state, explicit_tracking
from governor.pa_source_disposition import KINDS, non_obligation_kind, non_obligation_decision, task_quality_category, event_notice, event_source_evidence

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


def _uid_search(client, *criteria):
    """Issue UID SEARCH without IMAP4.search()'s charset placeholder."""
    return client.uid("search", *criteria)

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

def has_explicit_no_action_required(compact):
    """Detect clear no-action language in plain text or HTML email content."""
    if sign_in_event(compact):
        return False
    text=" ".join(
        str(compact.get(field) or "")
        for field in ("subject","snippet","body","text")
    )
    # Inline HTML can split a phrase across nodes, e.g. "No action <span>required</span>."
    text=html.unescape(text)
    text=re.sub(r"<[^>]*>", " ", text)
    text=re.sub(r"[\u200b-\u200f\ufeff]", "", text)
    text=re.sub(r"\s+", " ", text)
    return bool(re.search(
        r"\bno\s+(?:further\s+)?action\s+(?:is\s+)?required\b",
        text,
        re.IGNORECASE,
    ))

def insurance_quote_only(message):
    """Quote offers alone cannot establish an existing-policy renewal obligation."""
    subject=html.unescape(str(message.get("subject") or ""))
    body=html.unescape(" ".join(str(message.get(k) or "") for k in ("body","text","snippet")))
    text=re.sub(r"<[^>]*>"," ",subject+" "+body)
    if not re.search(r"\b(?:insurance|insurer|policy|cover)\b",text,re.I):return False
    quote=bool(re.search(r"\b(?:quotes?|quotations?)\b",subject,re.I) or re.search(r"\b(?:this is (?:only |just )?a quote|your (?:insurance )?quotes?|(?:insurance|renewal) quotes?|quotation (?:reference|details)|not (?:an? )?(?:insurance )?policy)\b",text,re.I))
    policy=bool(re.search(r"\b(?:your (?:current|existing) policy|your policy (?:expires|ends|renews)|renewal (?:notice|invitation)|certificate of (?:motor )?insurance|policy (?:has been issued|is now active)|cover is (?:now )?in force)\b",text,re.I))
    request=bool(re.search(r"\b(?:please|you (?:must|need to))\s+(?:review|confirm|correct|provide|send|pay|sign)\b",text,re.I))
    return quote and not policy and not request


def hold_quote_only_obligation(task,sources):
    ids=task_source_message_ids(task)
    if insurance_matter(task):
        task["quote_source_diagnostics"]={"sources":len(ids),"missing":sum(source not in sources for source in ids),"quote_only":sum(source in sources and insurance_quote_only(sources[source]) for source in ids),"verified_policy_date":task.get("due_date_source")=="paperless_policy"}
    if (not insurance_matter(task) or not ids or task.get("due_date_source")=="paperless_policy"
            or not all(source in sources and insurance_quote_only(sources[source]) for source in ids)):
        return False
    task["obligation_suppressed"]="quote_only_no_verified_policy"
    return True


def sign_in_event(message):
    """Recognise a reported OpenAI sign-in, not generic advice or an OTP.

    Sender naming is a routing hint, not sender authentication. No email URLs
    are trusted, and an email timestamp is never called a sign-in timestamp.
    """
    sender=parseaddr(str(message.get("from") or ""))[1].lower()
    domain=sender.rpartition("@")[2]
    if domain != "openai.com" and not domain.endswith(".openai.com"):
        return None
    source_id=str(message.get("message_id") or "")
    if not source_id.startswith("<") or not source_id.endswith(">") or "@" not in source_id:
        return None
    subject=html.unescape(str(message.get("subject") or ""))
    body=html.unescape(str(message.get("body") or ""))
    text=re.sub(r"<[^>]*>"," ",subject+"\n"+body)
    text=re.sub(r"[\u200b-\u200f\ufeff]","",text)
    if re.search(r"\b(?:one[- ]time (?:password|code)|verification code|password reset|reset your password)\b",subject,re.I):
        return None
    if not re.search(r"\b(?:login|log in|sign[- ]?in)\b",text,re.I):
        return None
    if not re.search(r"\b(?:new (?:login|sign[- ]?in)|did you (?:just )?(?:log|sign) in|(?:login|sign[- ]?in) (?:alert|attempt|detected|from a new device))\b",text,re.I):
        return None
    try: received=int(parsedate_to_datetime(str(message.get("date") or "")).timestamp())
    except (TypeError,ValueError,OverflowError): received=None
    return {"id":hashlib.sha256(source_id.encode()).hexdigest(),
            "source_message_id":source_id,"provider":"OpenAI",
            "email_received_at":received,
            "device":None,"location":None,"sign_in_time":None}


def refresh_sign_in_events(task,sources):
    existing={event["source_message_id"]:event for event in task.get("sign_in_events") or [] if isinstance(event,dict) and event.get("source_message_id")}
    ids=task_source_message_ids(task)
    for source_id in ids:
        if source_id in sources:
            event=sign_in_event(sources[source_id])
            if event:existing[source_id]=event
            else:existing.pop(source_id,None)
    task["sign_in_events"]=[existing[key] for key in ids if key in existing][-20:]


def hold_source_non_obligation(task,sources,user_state):
    ids=task_source_message_ids(task)
    decisions={source:non_obligation_decision(sources[source]) for source in ids if source in sources}
    event_evidence={source:event_source_evidence(sources[source],task.get("due_date")) for source in ids if source in sources}
    kinds={source:decision[0] for source,decision in decisions.items()}
    entry=(user_state.get("obligations") or {}).get(task.get("id"))
    protected=explicit_tracking(entry)
    user_closed=isinstance(entry,dict) and entry.get("status_override") in {"DONE","DISMISSED"}
    task["source_disposition_checks"]={"sources":len(ids),"missing":len(ids)-len(kinds),
        "non_obligation":sum(bool(kind) for kind in kinds.values()),"user_tracking":protected,"user_closed":user_closed,
        "kind_counts":{kind:sum(value==kind for value in kinds.values()) for kind in sorted(KINDS)},
        "event_notices":sum(event_notice(sources[source]) for source in ids if source in sources),
        "event_schedules":sum(bool(value.get("event_scheduled")) for value in event_evidence.values()),
        "event_date_matches":sum(bool(value.get("event_date_matches")) for value in event_evidence.values()),
        "event_action_deadlines":sum(bool(value.get("event_action_deadline")) for value in event_evidence.values()),
        "event_action_signals":sum(bool(value.get("event_action_signal")) for value in event_evidence.values()),
        "reason_counts":{reason:sum(decision[1]==reason for decision in decisions.values()) for reason in ("mandatory_request","accepted_commitment","transactional_or_subject_uncertainty","unclassified")}}
    prior=task.get("obligation_suppressed")
    managed=prior in KINDS or prior=="non_obligation_updates"
    if prior=="quote_only_no_verified_policy" or task.get("sign_in_events"):
        return False
    if protected or user_closed:
        if managed:task.pop("obligation_suppressed",None)
        return False
    if managed and any(kind is None for kind in kinds.values()):
        task.pop("obligation_suppressed",None)
    if ids and len(kinds)==len(ids) and all(kinds.values()):
        unique=set(kinds.values())
        task["obligation_suppressed"]=next(iter(unique)) if len(unique)==1 else "non_obligation_updates"
        return True
    # A temporary lookup miss is not evidence that the source changed.
    return False


def flag_unconfirmed_commitment(task,user_state):
    task.pop("confirmation_required",None)
    task.pop("source_response_required",None)
    entry=(user_state.get("obligations") or {}).get(task.get("id"))
    date_verified=bool(isinstance(entry,dict) and entry.get("due_date_override")) or task.get("due_date_source")=="paperless_policy"
    if date_verified:
        task.pop("date_confirmation_required",None)
    if (task.get("obligation_suppressed") or task.get("sign_in_events") or explicit_tracking(entry)
            or isinstance(entry,dict) and entry.get("status_override") in {"DONE","DISMISSED"}
            or task.get("status") not in {"OPEN","WAITING"}):
        return
    checks=task.get("source_disposition_checks") or {}
    if checks.get("missing",0)>0:
        task["confirmation_required"]="source_unavailable"
        if task.get("due_date") and not date_verified:task["date_confirmation_required"]=True
    elif task_quality_category(task)=="scheduled_event" and not date_verified:
        try: elapsed=date.fromisoformat(str(task.get("due_date")))<date.today()
        except (TypeError,ValueError):elapsed=False
        if (elapsed and checks.get("sources",0)>0 and checks.get("missing",0)==0
                and checks.get("event_schedules")==checks.get("sources")
                and checks.get("event_date_matches")==checks.get("sources")
                and checks.get("event_action_deadlines",0)==0):
            task["confirmation_required"]="past_event_status"
            task["date_confirmation_required"]=True
            reasons=checks.get("reason_counts") or {}
            task["source_response_required"]=(checks.get("event_notices",0)!=checks.get("sources",0)
                or checks.get("event_action_signals",0)>0
                or any(reasons.get(reason,0) for reason in ("mandatory_request","accepted_commitment","transactional_or_subject_uncertainty")))
    elif task_quality_category(task) in {"optional_opportunity","optional_feedback","optional_change_window"} and not date_verified:
        reasons=checks.get("reason_counts") or {}
        if (checks.get("sources",0)>0 and reasons.get("unclassified",0)>0
                and not any(reasons.get(key,0) for key in ("mandatory_request","accepted_commitment","transactional_or_subject_uncertainty"))):
            task["confirmation_required"]="optional_commitment"
            if task.get("due_date") and not date_verified:task["date_confirmation_required"]=True


def classify(compact):
    event=sign_in_event(compact)
    if event:
        return {"relevant":True,"actionable":True,"title":"Was this OpenAI sign-in you?",
                "status":"OPEN","due_date":None,"counterparty":"OpenAI",
                "topic":"Account sign-in "+event["id"][:16],"severity":"normal",
                "evidence_query":"","reason":"Source email reports a sign-in requiring user confirmation."}
    disposition=non_obligation_kind(compact)
    if disposition:
        return {"relevant":True,"actionable":False,"title":"Information update",
                "status":"NONE","due_date":None,"counterparty":None,"topic":"Source update",
                "severity":"normal","evidence_query":"","reason":"Source is "+disposition+", not an accepted commitment."}
    prompt="""You are LifeOS local personal-administration task extraction. Decide whether this email creates, updates, or completes something the user must track. Ignore marketing, newsletters, OTPs, FYI-only mail and ordinary parcel tracking. Return JSON only:
{"relevant":true|false,"actionable":true|false,"title":"short task or event","status":"OPEN|WAITING|DONE|NONE","due_date":"YYYY-MM-DD or null","counterparty":"short name or null","topic":"stable short matter topic","severity":"LOW|NORMAL|HIGH","evidence_query":"terms useful for Paperless search","reason":"short"}
Mark relevant=true for a meaningful update to an existing matter, including informational updates that do not create an obligation. Mark relevant=false for junk, marketing, newsletters, OTPs, generic FYI and ordinary parcel tracking. Do not create obligations from informative events. Offers, discount expiry dates and invitations to apply are optional, not user commitments; require evidence that the user accepted/applied/booked or is personally required to act. Ordinary delivery status is information unless there is a delivery exception or a concrete required response. A past date alone does not prove completion or make an optional offer an overdue task. Do not invent dates or completion. A request, deadline, renewal, claim, appointment preparation, payment/action required, application/process awaiting another party, or explicit resolution may be trackable. Use DONE only when the email itself clearly resolves the tracked matter.
EMAIL:
"""+json.dumps(compact,ensure_ascii=False)
    d=parse_json(ai_broker._ollama(prompt,ai_broker.OLLAMA_MODEL,response_format=TASK_CLASSIFICATION_SCHEMA))
    if not isinstance(d,dict) or not isinstance(d.get("actionable"),bool): raise ValueError("invalid schema")
    if "relevant" not in d:d["relevant"]=bool(d["actionable"])
    if not isinstance(d.get("relevant"),bool): raise ValueError("invalid relevance")
    if str(d.get("status")) not in {"OPEN","WAITING","DONE","NONE"}: raise ValueError("invalid status")
    severity=str(d.get("severity","normal")).lower()
    d["severity"]=severity if severity in {"low","normal","high"} else "normal"
    if insurance_quote_only(compact):
        d.update(actionable=False,status="NONE",relevant=True,due_date=None,reason="Quote offer is informational, not a policy renewal obligation.")
    explicit_no_action=has_explicit_no_action_required(compact)
    if explicit_no_action:
        # Explicit source wording outranks a model guess that an FYI notice
        # creates work. Keep the source as an informational update only.
        d["actionable"]=False
        d["status"]="NONE"
        d["relevant"]=True
        d["reason"]="The email explicitly says no action is required."
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
    """Extract stable identifiers that can safely connect related messages."""
    text=" ".join(str(msg.get(field,"")) for field in ("subject","body"))
    labels=(
        r"case(?:\s*(?:id|no\.?|number|ref(?:erence)?))?"
        r"|claim(?:\s*(?:id|no\.?|number|ref(?:erence)?))?"
        r"|(?:purchase\s+)?order(?:\s*(?:id|no\.?|number|ref(?:erence)?))?"
        r"|tracking(?:\s*(?:id|no\.?|number|code|ref(?:erence)?))?"
        r"|shipment(?:\s*(?:id|no\.?|number|ref(?:erence)?))?"
        r"|consignment(?:\s*(?:id|no\.?|number|ref(?:erence)?))?"
        r"|parcel\s+tracking(?:\s*(?:id|no\.?|number|code|ref(?:erence)?))?"
        r"|parcel(?:\s*(?:id|no\.?|number|ref(?:erence)?))?"
        r"|policy\s*(?:id|no\.?|number|ref(?:erence)?)"
        r"|reference|ref"
    )
    pattern=rf"\b(?:{labels})\s*(?:(?:is|number)\s*){{0,2}}[:#=-]?\s*([A-Z0-9][A-Z0-9/_-]{{2,39}})\b"
    values=set()
    for match in re.finditer(pattern,text,re.IGNORECASE):
        normalized=re.sub(r"[^A-Z0-9]","",match.group(1).upper())
        if 4<=len(normalized)<=40 and any(ch.isdigit() for ch in normalized):
            values.add(normalized)
    return values

def verified_message_documents(candidates, message_ids, matter_reference_ids, document_loader):
    """Keep documents explicitly tied by source Message-ID or labelled ID.

    Paperless full-text search is a candidate finder, not proof of a relationship.
    Accept exact email identity or a shared, labelled order/tracking/case ID so
    that merchant and courier messages can join without broad keyword matches.
    """
    source_ids={str(value).strip().casefold() for value in message_ids or [] if str(value or "").strip()}
    matter_ids={str(value).strip().upper() for value in matter_reference_ids or [] if str(value or "").strip()}
    verified=[]
    seen=set()
    for candidate in candidates or []:
        if not isinstance(candidate,dict):
            continue
        document_id=candidate.get("document_id")
        if not str(document_id or "").isdigit() or str(document_id) in seen:
            continue
        document=document_loader(int(document_id))
        if not isinstance(document,dict):
            continue
        content=str(document.get("content") or "")
        direct_match=any(source_id in content.casefold() for source_id in source_ids)
        document_refs=case_reference_ids({"body":content})
        reference_match=bool(matter_ids & document_refs)
        if not direct_match and not reference_match:
            continue
        seen.add(str(document_id))
        verified.append({
            "document_id":int(document_id),
            "title":str(document.get("title") or candidate.get("title") or "Paperless document")[:200],
            "created":str(document.get("created") or candidate.get("created") or "")[:40],
        })
        if len(verified)>=10:
            break
    return verified

def paperless_linked_documents(message_ids, matter_reference_ids=None):
    """Find Paperless documents tied by exact email or labelled order/case IDs."""
    ids=list(dict.fromkeys(str(value).strip() for value in message_ids or [] if str(value or "").strip()))
    matter_ids=sorted({str(value).strip() for value in matter_reference_ids or [] if str(value or "").strip()})
    candidates=[]
    seen=set()
    # Keep discovery bounded. Search results are untrusted candidates; every
    # document is checked for the exact source identity or a labelled ID below.
    # Search stable matter references first: recent courier/merchant emails may
    # have many source IDs, but the shared order/tracking ID is the key bridge.
    queries=(matter_ids[-10:]+ids[-10:])[:20]
    for query in queries:
        for candidate in paperless_search(query):
            document_id=str(candidate.get("document_id") or "")
            if document_id not in seen:
                candidates.append(candidate)
                seen.add(document_id)
                if len(candidates)>=50:
                    break
        if len(candidates)>=50:
            break
    return verified_message_documents(candidates,ids,matter_ids,_paperless_document)

def task_source_message_ids(task):
    """Collect known email identities, including records created before source lists existed."""
    values={str(value).strip() for value in task.get("source_message_ids") or [] if str(value or "").strip()}
    values.update(
        str(event.get("message_id")).strip()
        for event in task.get("timeline_events") or []
        if isinstance(event,dict) and str(event.get("message_id") or "").strip()
    )
    primary=str(task.get("email_message_id") or "").strip()
    if primary:
        values.add(primary)
    ordered=sorted(values)
    if primary:
        ordered=[value for value in ordered if value != primary]+[primary]
    return ordered[-20:]

def task_cleanup_source_message_id(task):
    """Choose the exact primary email, or a sole timeline source for legacy rows."""
    values=set(task_source_message_ids(task))
    primary=str(task.get("email_message_id") or "").strip()
    if primary and primary in values:
        return primary
    event_ids={
        str(event.get("message_id") or "").strip()
        for event in task.get("timeline_events") or []
        if isinstance(event,dict) and str(event.get("message_id") or "").strip()
    }
    if len(event_ids)==1:
        event_id=next(iter(event_ids))
        if event_id in values:
            return event_id
    if len(values)==1:
        return next(iter(values))
    return ""


def has_valid_source_email(task):
    """Return whether a task retains at least one usable RFC822 Message-ID."""
    for value in task_source_message_ids(task):
        message_id=str(value or "").strip()
        if (len(message_id)<=300 and message_id.startswith("<") and message_id.endswith(">")
                and "@" in message_id
                and not any(ord(ch)<32 or ch in (chr(34),chr(92),"<",">") for ch in message_id[1:-1])):
            return True
    return False


def discard_single_source_no_action_task(tasks,msg):
    """Remove an old false-positive task sourced only from this no-action email."""
    message_id=str(msg.get("message_id") or msg.get("source_ref") or "").strip()
    if not message_id:
        return False
    matches=[]
    for task_id,task in tasks.items():
        if not isinstance(task,dict):
            continue
        source_ids=set(task_source_message_ids(task))
        primary_id=str(task.get("email_message_id") or "").strip()
        event_ids={
            str(event.get("message_id") or "").strip()
            for event in task.get("timeline_events") or []
            if isinstance(event,dict) and event.get("message_id")
        }
        # Legacy rows may lack a primary field while retaining extra provenance
        # IDs. The sole timeline event is a safe fallback identity in that case.
        if (message_id in source_ids and event_ids=={message_id}
                and (primary_id==message_id or not primary_id)):
            matches.append(task_id)
    if len(matches)!=1:
        return False
    tasks.pop(matches[0],None)
    return True


def refresh_task_paperless_evidence(task):
    evidence=paperless_linked_documents(
        task_source_message_ids(task),
        task.get("case_reference_ids") or [],
    )
    combined={str(item.get("document_id")):item for item in (task.get("paperless_evidence") or []) if isinstance(item,dict) and str(item.get("document_id") or "").isdigit()}
    combined.update({str(item["document_id"]):item for item in evidence})
    task["paperless_evidence"]=list(combined.values())[:10]
    return task["paperless_evidence"]

def insurance_matter(task):
    label=" ".join(str(task.get(field) or "") for field in ("title","topic","counterparty"))
    return bool(re.search(r"\b(?:car|vehicle|motor)?\s*(?:insurance|insurer|policy)\b|\brenew(?:al|ing)\b",label,re.I))


def _parse_policy_date(value):
    value=str(value or "").strip()
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%d %B %Y","%d %b %Y"):
        try:return datetime.strptime(value,fmt).date().isoformat()
        except ValueError:pass
    return ""


def policy_renewal_dates(content):
    """Extract dates only when OCR places them beside an explicit policy end/renewal label."""
    text=str(content or "")
    date_pattern=r"(?:20\d{2}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})"
    label_pattern=re.compile(
        r"\b(?:renewal\s+(?:date|due)|renew(?:s|al)?\s+on|"
        r"policy\s+expires|cover\s+expires|expires\s+on|expiry\s+date|"
        r"end\s+date\s+of\s+(?:the\s+)?cover)\b",
        re.I,
    )
    dates=set()
    for label in label_pattern.finditer(text):
        window=text[label.end():label.end()+180]
        # The first date after a renewal/expiry label is its value; later
        # dates in the paragraph may be issue or print dates.
        match=re.search(date_pattern,window,re.I)
        if match:
            parsed=_parse_policy_date(match.group(0))
            if parsed:dates.add(parsed)
    # Policy schedules commonly express the cover period as a start/end range.
    for match in re.finditer(
        rf"\bperiod\s+of\s+(?:insurance|cover)\b[^\n]{{0,100}}?({date_pattern})\s*(?:to|through|[-–])\s*({date_pattern})",
        text,re.I,
    ):
        parsed=_parse_policy_date(match.group(2))
        if parsed:dates.add(parsed)
    return dates


def reconcile_insurance_policy_due_date(task):
    """Use a verified policy document as the renewal-date authority.

    For insurance tasks, discard an email/model-derived due date unless a verified
    Paperless document explicitly identifies one unambiguous renewal or cover end
    date. This prevents the reminder's arrival date becoming an overdue renewal.
    """
    if not insurance_matter(task):
        return False
    message_ids=task_source_message_ids(task)
    references=task.get("case_reference_ids") or []
    verified=verified_message_documents(
        task.get("paperless_evidence") or [],message_ids,references,_paperless_document,
    )
    dates=set()
    for item in verified:
        document=_paperless_document(item["document_id"])
        if not isinstance(document,dict):
            continue
        content=str(document.get("content") or "")
        if (not insurance_quote_only({"subject":document.get("title",""),"body":content})
                and re.search(r"\b(?:insurance|policy|cover|renewal)\b",content,re.I)):
            dates.update(policy_renewal_dates(content))
    # Require one clear date. If evidence is absent, unreadable, or conflicting,
    # keep the matter open without falsely labeling the reminder overdue.
    if len(dates)==1:
        task["due_date"]=next(iter(dates))
        task["due_date_source"]="paperless_policy"
    else:
        task["due_date"]=None
        task["due_date_source"]="unverified_insurance_policy"
    task["paperless_evidence"]=verified
    return True


def persist_task_paperless_evidence(task):
    """Publish refreshed verified document metadata without replacing task state."""
    task_id=str(task.get("id") or "")
    if not task_id:
        return
    for path in (STATE,OUT):
        try:
            payload=json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError,json.JSONDecodeError,OSError):
            continue
        changed=False
        for bucket in ("tasks","resolved", "informational"):
            for row in payload.get(bucket) or []:
                if isinstance(row,dict) and row.get("id")==task_id:
                    row["paperless_evidence"]=list(task.get("paperless_evidence") or [])[:10]
                    changed=True
        if not changed:
            continue
        temp=path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        try:
            metadata=path.stat()
            os.chmod(temp,metadata.st_mode & 0o7777)
            os.chown(temp,metadata.st_uid,metadata.st_gid)
        except OSError:
            temp.unlink(missing_ok=True)
            raise
        os.replace(temp,path)


def reverify_saved_task_paperless_evidence(task):
    """Retain only previously linked documents whose contents still prove identity."""
    message_ids=set(task_source_message_ids(task))
    task["paperless_evidence"]=verified_message_documents(
        task.get("paperless_evidence") or [],
        message_ids,
        task.get("case_reference_ids") or [],
        _paperless_document,
    )
    return task["paperless_evidence"]

def verified_source_email_requires_no_action(task):
    """Find a verified Paperless OCR copy of a task's sole source email that says no action is required."""
    source_ids=task_source_message_ids(task)
    if len(source_ids)!=1:
        return ""
    source_id=source_ids[0].casefold()
    verified=verified_message_documents(
        task.get("paperless_evidence") or [],
        source_ids,
        task.get("case_reference_ids") or [],
        _paperless_document,
    )
    for item in verified:
        document=_paperless_document(item["document_id"])
        if not isinstance(document,dict):
            continue
        content=str(document.get("content") or "")
        # Require the exact email identity in the OCR. A related policy or
        # courier document must never suppress the task just because it has
        # similar wording.
        if source_id in content.casefold() and has_explicit_no_action_required({"body":content}):
            return source_ids[0]
    return ""


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
    refresh_task_paperless_evidence(task)
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
        rows=(data.get("tasks") or [])+(data.get("resolved") or [])+(data.get("informational") or [])
        previous={}
        for x in rows:
            if not isinstance(x,dict) or not x.get("id"): continue
            item=dict(x)
            # Treat saved IDs as candidates, then re-check their full text
            # before publishing. This lets already-processed emails retain
            # valid links without restoring legacy broad-search false matches.
            if str(item.get("machine_status") or "").upper() in {"OPEN","WAITING","DONE","DISMISSED"}:
                item["status"]=item["machine_status"]
            if "machine_due_date" in item:
                item["due_date"]=item.pop("machine_due_date")
                item["due_date_source"]=item.pop("machine_due_date_source",None)
                if item.pop("machine_date_confirmation_required",False):item["date_confirmation_required"]=True
                else:item.pop("date_confirmation_required",None)
            if "machine_severity" in item:
                item["severity"]=item.pop("machine_severity")
                item["severity_source"]=item.pop("machine_severity_source",None)
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

_SOURCE_LOOKUP_DIAGNOSTICS={}

def fetch_existing_task_source_emails(tasks, already_fetched=(), client=None):
    """Fetch exact saved source emails and keep lookup diagnostics aggregate."""
    global _SOURCE_LOOKUP_DIAGNOSTICS
    known={str(value).strip() for value in already_fetched if str(value or "").strip()}
    message_ids=set()
    source_dates={}
    single_source_tasks=0
    valid_source_ids=0
    tasks_already_fetched=0
    tasks_missing_date=0
    date_windows=0
    date_window_uids=0
    fetch_attempts=0
    exact_id_matches=0
    lookup_query_errors=0
    tasks_seen=0
    tasks_with_source_ids=0
    tasks_without_source_ids=0
    tasks_with_primary=0
    tasks_without_primary=0
    tasks_multi_source_without_primary=0
    timeline_source_fallback_tasks=0
    task_rows=list(tasks or [])
    tasks_seen=len(task_rows)
    for task in task_rows:
        ids=task_source_message_ids(task)
        if ids:
            tasks_with_source_ids+=1
        else:
            tasks_without_source_ids+=1
            continue
        if len(ids)==1:
            single_source_tasks+=1
        primary_id=str(task.get("email_message_id") or "").strip()
        if primary_id:
            tasks_with_primary+=1
        else:
            tasks_without_primary+=1
        # Prefer the explicit primary ID. For a legacy row with several
        # provenance IDs, inspect a sole timeline event only when the primary
        # field is absent; the cleanup guard below also requires that sole event.
        message_id=primary_id if primary_id in ids else ""
        if not message_id and not primary_id:
            event_ids={
                str(event.get("message_id") or "").strip()
                for event in task.get("timeline_events") or []
                if isinstance(event,dict) and str(event.get("message_id") or "").strip()
            }
            if len(event_ids)==1:
                candidate=next(iter(event_ids))
                if candidate in ids:
                    message_id=candidate
                    timeline_source_fallback_tasks+=1
            if len(ids)>1:
                tasks_multi_source_without_primary+=1
        if not message_id and len(ids)==1:
            message_id=ids[0]
        if not message_id:
            continue
        if (message_id not in known and len(message_id)<=300 and message_id.startswith("<")
                and message_id.endswith(">") and "@" in message_id
                and not any(ord(ch)<32 or ch in (chr(34),chr(92),"<",">") for ch in message_id[1:-1])):
            valid_source_ids+=1
            message_ids.add(message_id)
            for event in reversed(task.get("timeline_events") or []):
                if isinstance(event,dict) and str(event.get("message_id") or "").strip()==message_id and event.get("date"):
                    source_dates[message_id]=str(event["date"])
                    break
            if message_id not in source_dates and task.get("email_message_id")==message_id:
                source_dates[message_id]=str(task.get("updated_from_email") or "")
            if not source_dates.get(message_id):
                tasks_missing_date+=1
        elif message_id in known:
            tasks_already_fetched+=1
    if not message_ids:
        for key,value in (
            ("TASKS_SEEN",tasks_seen),
            ("TASKS_WITH_SOURCE_IDS",tasks_with_source_ids),
            ("TASKS_WITHOUT_SOURCE_IDS",tasks_without_source_ids),
            ("TASKS_WITH_PRIMARY",tasks_with_primary),
            ("SINGLE_SOURCE_TASKS",single_source_tasks),
            ("VALID_IDS",valid_source_ids),
            ("ALREADY_FETCHED",tasks_already_fetched),
            ("MISSING_DATES",tasks_missing_date),
            ("TASKS_WITHOUT_PRIMARY",tasks_without_primary),
            ("MULTI_SOURCE_WITHOUT_PRIMARY",tasks_multi_source_without_primary),
            ("TIMELINE_FALLBACK_TASKS",timeline_source_fallback_tasks),
        ):
            print("TASK_STALE_SOURCE_LOOKUP_"+key+"="+str(value),flush=True)
        for key in ("DATE_WINDOWS","DATE_UIDS","FETCH_ATTEMPTS","EXACT_MATCHES"):
            print("TASK_STALE_SOURCE_LOOKUP_"+key+"=0",flush=True)
        _SOURCE_LOOKUP_DIAGNOSTICS={
            "tasks_seen":tasks_seen,"tasks_with_source_ids":tasks_with_source_ids,
            "tasks_without_source_ids":tasks_without_source_ids,"tasks_with_primary":tasks_with_primary,
            "single_source_tasks":single_source_tasks,"valid_ids":valid_source_ids,
            "already_fetched":tasks_already_fetched,"missing_dates":tasks_missing_date,
            "tasks_without_primary":tasks_without_primary,
            "multi_source_without_primary":tasks_multi_source_without_primary,
            "timeline_fallback_tasks":timeline_source_fallback_tasks,
            "date_windows":0,"date_window_uids":0,"fetch_attempts":0,"exact_id_matches":0,
        }
        return {}
    owns_client=client is None
    if owns_client:
        user=secret("LIFEOS_IMAP_USER",("gmail-imap-user","imap-user","gmail-user"))
        password=secret("LIFEOS_IMAP_PASSWORD",("gmail-imap-password","imap-password","gmail-app-password"))
        client=imaplib.IMAP4_SSL(
            os.getenv("LIFEOS_IMAP_HOST","imap.gmail.com"),
            int(os.getenv("LIFEOS_IMAP_PORT","993")),
            ssl_context=ssl.create_default_context(),
        )
    # Publish the task-side counts before any network operation so a mailbox
    # error cannot make a populated state look like zero tasks were inspected.
    _SOURCE_LOOKUP_DIAGNOSTICS={
        "tasks_seen":tasks_seen,"tasks_with_source_ids":tasks_with_source_ids,
        "tasks_without_source_ids":tasks_without_source_ids,"tasks_with_primary":tasks_with_primary,
        "single_source_tasks":single_source_tasks,"valid_ids":valid_source_ids,
        "already_fetched":tasks_already_fetched,"missing_dates":tasks_missing_date,
        "tasks_without_primary":tasks_without_primary,
        "multi_source_without_primary":tasks_multi_source_without_primary,
        "timeline_fallback_tasks":timeline_source_fallback_tasks,
        "date_windows":0,"date_window_uids":0,"fetch_attempts":0,"exact_id_matches":0,
        "lookup_failed":0,"lookup_query_errors":0,
    }
    result={}
    archive_mailboxes_checked=0
    archive_exact_matches=0
    chosen_mailbox=None
    lookup_phase="mailbox_select"
    _SOURCE_LOOKUP_DIAGNOSTICS["lookup_phase"]=lookup_phase
    try:
        if owns_client:
            client.login(user,password)
        # The reconciler's shared IMAP session is already selected on
        # INBOX. Do not probe All Mail names on that session: a rejected
        # SELECT can invalidate its selected state before source searches.
        selected=not owns_client
        if owns_client:
            for mailbox in ("INBOX","[Gmail]/All Mail","[GoogleMail]/All Mail"):
                try:
                    status,_=client.select(mailbox,readonly=True)
                except imaplib.IMAP4.error:
                    continue
                if status=="OK":
                    selected=True
                    chosen_mailbox=mailbox
                    break
        if not selected:
            raise RuntimeError("imap_all_mail_unavailable")
        # Only the fresh owned session may select archive folders. Shared
        # caller sessions retain their existing selected-mailbox state.
        mailbox_sequence=[None]+([name for name in ("[Gmail]/All Mail","[GoogleMail]/All Mail") if name!=chosen_mailbox] if owns_client else [])
        for archive_mailbox in mailbox_sequence:
            if not (message_ids-set(result)):
                break
            if archive_mailbox is not None:
                archive_mailboxes_checked+=1
                try:
                    status,_=client.select(archive_mailbox,readonly=True)
                except imaplib.IMAP4.error:
                    continue
                if status!="OK":
                    continue
            for message_id in sorted(message_ids-set(result)):
                lookup_phase="header_search"
                _SOURCE_LOOKUP_DIAGNOSTICS["lookup_phase"]=lookup_phase
                # IMAP4.uid passes search arguments verbatim (unlike search()).
                # Quote search strings explicitly so RFC822 Message-IDs with <>/@
                # remain one valid IMAP astring.
                quoted_message_id='"'+message_id.replace("\\","\\\\").replace('"','\\"')+'"'
                try:
                    status,rows=client.uid("search","HEADER","Message-ID",quoted_message_id)
                except imaplib.IMAP4.error:
                    lookup_query_errors+=1
                    status,rows="NO",[]
                matches=rows[0].split() if status=="OK" and rows else []
                if len(matches)!=1:
                    # Gmail's message-ID search operator is a fallback for servers
                    # that do not match RFC822 header values consistently. The
                    # fetched RFC822 header is still checked against the exact ID.
                    raw_message_id=message_id[1:-1]
                    lookup_phase="gmail_raw_search"
                    _SOURCE_LOOKUP_DIAGNOSTICS["lookup_phase"]=lookup_phase
                    quoted_gmail_query='"rfc822msgid:'+raw_message_id.replace("\\","\\\\").replace('"','\\"')+'"'
                    try:
                        status,rows=client.uid("search","X-GM-RAW",quoted_gmail_query
                        )
                    except imaplib.IMAP4.error:
                        lookup_query_errors+=1
                        status,rows="NO",[]
                    matches=rows[0].split() if status=="OK" and rows else []
                if len(matches)!=1:
                    # Some Gmail IMAP deployments do not return results for either
                    # exact Message-ID search form. Use the saved source date to
                    # scan a small mailbox window, then require an exact RFC822
                    # Message-ID match before accepting any email as task evidence.
                    try:
                        source_date=parsedate_to_datetime(source_dates.get(message_id,"")).date()
                    except (TypeError,ValueError,OverflowError):
                        source_date=None
                    date_uids=[]
                    if source_date:
                        start=(source_date-timedelta(days=1)).strftime("%d-%b-%Y")
                        end=(source_date+timedelta(days=2)).strftime("%d-%b-%Y")
                        date_windows+=1
                        lookup_phase="date_window_search"
                        _SOURCE_LOOKUP_DIAGNOSTICS["lookup_phase"]=lookup_phase
                        try:
                            status,rows=client.uid("search","SINCE",start,"BEFORE",end)
                        except imaplib.IMAP4.error:
                            lookup_query_errors+=1
                            status,rows="NO",[]
                        date_uids=(rows[0].split() if status=="OK" and rows else [])[-200:]
                  …29423 tokens truncated…is.";
          dialog.innerHTML = this._reviewDialogMarkup(latest, dialog._reviewBusyText, dialog._reviewPreviews || []);
          this._bindReviewDialog(dialog, taskId);
          return;
        }
        dialog._reviewBusyText = "Analysis is still running locally…";
        const status = dialog.querySelector("[aria-live]");
        if (status) status.textContent = dialog._reviewBusyText;
        poll();
      };
      poll();
    } catch (_) {
      window.alert("LifeOS could not queue the local task analysis.");
      if (refresh) refresh.disabled = false;
    }
  }

  _showTaskReview(task) {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-labelledby", "review-title");
    dialog._reviewBusyText = "Loading the private document text preview…";
    dialog.innerHTML = this._reviewDialogMarkup(task, dialog._reviewBusyText);
    this.shadowRoot.append(dialog);
    this._activeReviewDialog = dialog;
    dialog.addEventListener("close", () => {
      this._hass.callApi("DELETE", "lifeos_pa_review/" + encodeURIComponent(String(task.id))).catch(() => {});
      dialog.remove();
      this._activeReviewDialog = null;
      this._render();
    });
    this._bindReviewDialog(dialog, String(task.id));
    dialog.showModal();
    this._loadEmailOpsShadow(dialog, String(task.id));
    this._loadReviewPreviews(dialog, String(task.id)).then((loaded) => {
      if (!dialog.open) return;
      if (!loaded || !task.ai_review) this._requestTaskReview(dialog, String(task.id));
    });
  }

  async _loadReviewPreviews(dialog, taskId) {
    try {
      const payload = await this._hass.callApi("GET", "lifeos_pa_review/" + encodeURIComponent(taskId));
      if (!dialog.open || payload?.schema !== "lifeos_pa_task_previews_v1" || payload.task_id !== taskId || !Array.isArray(payload.documents)) return false;
      if (JSON.stringify(payload.documents) === JSON.stringify(dialog._reviewPreviews || null)) return true;
      dialog._reviewPreviews = payload.documents;
      const latest = this._items().find((x) => x.id === taskId);
      if (latest) {
        dialog.innerHTML = this._reviewDialogMarkup(latest, dialog._reviewBusyText || "", dialog._reviewPreviews);
        this._bindReviewDialog(dialog, taskId);
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  async _loadEmailOpsShadow(dialog, taskId) {
    try {
      const payload = await this._hass.callApi("GET", "lifeos_emailops_shadow/" + encodeURIComponent(taskId));
      if (!dialog.open || payload?.schema !== "lifeos_emailops_shadow_task_v1" || payload.task_id !== taskId || payload.mode !== "shadow") return;
      if (!this._emailopsReports) this._emailopsReports = new Map();
      this._emailopsReports.set(taskId, payload);
      const task = this._items().find((x) => x.id === taskId);
      if (task) {
        dialog.innerHTML = this._reviewDialogMarkup(task, dialog._reviewBusyText || "", dialog._reviewPreviews || []);
        this._bindReviewDialog(dialog, taskId);
      }
    } catch (_) { /* A task without a shadow sample keeps its normal review. */ }
  }


  async _showEmailSamples() {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-label", "Email suggestion review");
    dialog.innerHTML = '<p>Loading private samples…</p><button type="button">Close</button>';
    dialog.querySelector("button").onclick = () => dialog.close();
    this.shadowRoot.append(dialog);
    this._activeReviewDialog = dialog;
    dialog.addEventListener("close", () => { dialog.remove(); this._activeReviewDialog = null; this._render(); });
    dialog.showModal();
    try {
      const payload = await this._hass.callApi("GET", "lifeos_emailops_samples");
      if (!dialog.open) return;
      if (payload?.schema !== "lifeos_emailops_samples_v1" || !Array.isArray(payload.samples)) throw new Error();
      dialog.innerHTML = '<h2>Email suggestion review</h2><p>Comparison only. No task or mailbox changes.</p><p>Sampled ' +
        this._escape(new Date(payload.generated_at * 1000).toLocaleString()) + '</p>' +
        payload.samples.map((sample, i) => {
          const query = encodeURIComponent("rfc822msgid:" + String(sample.source_message_id).replace(/[<>]/g, ""));
          return '<section><h3>Sample ' + (i + 1) + (sample.matched ? ' · Existing task source' : ' · Not linked to a task') +
            '</h3><a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/0/#search/' + query +
            '">Open source email</a><p>' + this._escape(sample.summary || "No summary provided.") +
            '</p><h4>Suggested obligations</h4>' + (sample.proposals.length ? '<ul>' + sample.proposals.map(p =>
              '<li>' + this._escape(p.title) + (p.due_date ? ' · ' + this._escape(p.due_date) : '') + '</li>').join('') +
              '</ul>' : '<p>No obligation suggested.</p>') + '<p>Completion not assessed.</p></section>';
        }).join('') + '<button type="button" data-samples-close>Close</button>';
      dialog.querySelector("[data-samples-close]").onclick = () => dialog.close();
    } catch (_) {
      if (dialog.open) dialog.querySelector("p").textContent = "No current sample is available. Existing tasks are unchanged.";
    }
  }

  async _act(button) {
    let action = button.dataset.action;
    const taskId = button.dataset.id;
    const task = this._items().find((x) => x.id === taskId);
    if (!task) return;
    const label = task.title || taskId;
    const data = { action, task_id: taskId, note: "", until: "", severity: "", due_date: "" };
    if (action.startsWith("signin_")) {
      data.note = button.dataset.event || "";
      if (!/^[a-f0-9]{64}$/.test(data.note)) return;
    } else if (["reopen","dismiss"].includes(action) && task.confirmation_required) {
      // The labelled answer is the explicit user decision; no whole-source inference.
    } else if (action === "review") {
      this._showTaskReview(task);
      return;
    } else if (action === "junk") {
      const selected = await this._chooseJunkDocuments(task);
      if (!selected) return;
      data.paperless_ids = selected.join(",");
    } else if (action === "comment") {
      data.note = window.prompt("Add a note to " + label + ":") || "";
      if (!data.note.trim()) return;
      if (!window.confirm("Add this user note to the obligation?")) return;
    } else if (action === "snooze") {
      data.until = window.prompt("Snooze until (YYYY-MM-DD):", this._datePlusOne()) || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(data.until)) return;
      if (!window.confirm("Snooze " + label + " until " + data.until + "?")) return;
    } else if (action === "severity") {
      data.severity = window.prompt("Set severity: low, normal, or high:", task.severity || "normal") || "";
      if (!["low", "normal", "high"].includes(data.severity.toLowerCase())) return;
      data.severity = data.severity.toLowerCase();
      if (!window.confirm("Override severity for " + label + " to " + data.severity + "?")) return;
    } else if (action === "due_date") {
      data.due_date = window.prompt("Set due date (YYYY-MM-DD):", task.due_date || "") || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(data.due_date)) return;
      if (!window.confirm("Override due date for " + label + " to " + data.due_date + "?")) return;
    } else if (action !== "junk" && !window.confirm(action === "close" ? "Mark " + label + " complete?" :
      action === "dismiss" ? "Dismiss " + label + " as not a task?" :
      action === "reopen" ? (task.obligation_suppressed ? "Track this as your own task?" : "Reopen " + label + "?") : "Unsnooze " + label + "?")) return;

    button.disabled = true;
    try {
      await this._hass.callService("shell_command", "lifeos_pa_user_action", data);
      if (action === "junk") {
        window.alert("Junk request queued. The matter will close after the email and selected Paperless documents are verified.");
      }
      await this._hass.callService("homeassistant", "update_entity", { entity_id: this._entity() });
    } catch (error) {
      window.alert("LifeOS could not verify this action. The task view has not been confirmed updated.");
    } finally {
      button.disabled = false;
    }
  }
}

customElements.define("lifeos-pa-task-card", LifeOSPATaskCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "lifeos-pa-task-card",
  name: "LifeOS PA Tasks",
  description: "Source-backed matters, questions and daily actions",
});
