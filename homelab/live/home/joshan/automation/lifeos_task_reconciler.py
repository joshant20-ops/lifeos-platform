#!/usr/bin/env python3
"""LifeOS personal task reconciler.

Reads recent Gmail locally, extracts user obligations with governed local AI, and
reconciles them against Paperless evidence. Private content never leaves the host.
The published HA JSON contains only user-facing task summaries plus stable provenance.
"""
from __future__ import annotations
import email, hashlib, imaplib, json, os, re, ssl, sys, time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO=Path(os.getenv("LIFEOS_PLATFORM_REPO","/home/joshan/lifeos-platform"))
sys.path.insert(0,str(REPO))
from governor import ai_broker
from lifeos_email_paperless_selective import secret, paperless_token

HA=Path("/opt/stacks/homeassistant/config")
STATE=Path("/home/joshan/automation/state/lifeos_personal_tasks.json")
SCAN_STATE=Path("/home/joshan/automation/state/lifeos_personal_task_scan.json")
OUT=HA/"www/lifeos_tasks.json"
MAX_MESSAGES=int(os.getenv("LIFEOS_TASK_EMAIL_LIMIT","6"))
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
{"actionable":true|false,"title":"short task","status":"OPEN|WAITING|DONE|NONE","due_date":"YYYY-MM-DD or null","counterparty":"short name or null","topic":"stable short topic","evidence_query":"terms useful for Paperless search","reason":"short"}
Do not invent dates or completion. A request, deadline, renewal, claim, appointment preparation, payment/action required, application/process awaiting another party, or explicit resolution may be trackable. Use DONE only when the email itself clearly resolves the tracked matter.
EMAIL:
"""+json.dumps(compact,ensure_ascii=False)
    d=parse_json(ai_broker._ollama(prompt,ai_broker.OLLAMA_MODEL))
    if not isinstance(d,dict) or not isinstance(d.get("actionable"),bool): raise ValueError("invalid schema")
    if str(d.get("status")) not in {"OPEN","WAITING","DONE","NONE"}: raise ValueError("invalid status")
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

def thread_root(msg):
    refs=re.findall(r"<[^<>]+>",str(msg.get("references","")))
    if refs:return refs[0]
    replies=re.findall(r"<[^<>]+>",str(msg.get("in_reply_to","")))
    return replies[0] if replies else (str(msg.get("message_id") or msg.get("source_ref") or "")[:300])

def resolve_task_id(d,msg,tasks):
    semantic=key(d)
    refs=reference_ids(msg)
    ref_matches=[]
    legacy_matches=[]
    for task_id,task in tasks.items():
        known=set(task.get("source_message_ids") or [])
        if task.get("email_message_id"):known.add(str(task["email_message_id"]))
        if refs & known:ref_matches.append((task_id,task))
        same_legacy_message=str(task.get("email_message_id") or "")==str(msg.get("message_id") or "")
        has_no_source_ref=not task.get("email_message_id") and not task.get("source_message_ids")
        if not task.get("thread_root_id") and task.get("identity_semantic",task_id)==semantic and (same_legacy_message or has_no_source_ref):
            legacy_matches.append((task_id,task))
    semantic_matches=[x for x in ref_matches if x[1].get("identity_semantic")==semantic]
    if len(semantic_matches)==1:return semantic_matches[0][0]
    if len(ref_matches)==1:return ref_matches[0][0]
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
        return {str(x.get("id")):x for x in rows if isinstance(x,dict) and x.get("id")}
    except Exception:return {}

def load_scan_state():
    try:
        data=json.loads(SCAN_STATE.read_text())
        return data if data.get("schema")=="lifeos_task_scan_v1" else {}
    except Exception:return {}

def message_time(date_value):
    try:return int(parsedate_to_datetime(str(date_value or "")).timestamp())
    except Exception:return int(time.time())

def main():
    previous=load_previous()
    scan=load_scan_state()
    user=secret("LIFEOS_IMAP_USER",("gmail-imap-user","imap-user","gmail-user"))
    password=secret("LIFEOS_IMAP_PASSWORD",("gmail-imap-password","imap-password","gmail-app-password"))
    c=imaplib.IMAP4_SSL(os.getenv("LIFEOS_IMAP_HOST","imap.gmail.com"),int(os.getenv("LIFEOS_IMAP_PORT","993")),ssl_context=ssl.create_default_context())
    c.login(user,password);c.select("INBOX",readonly=True)
    try:
        _,validity_rows=c.response("UIDVALIDITY")
        uidvalidity=(validity_rows or [b""])[0].decode(errors="ignore")
    except Exception:
        uidvalidity=""
    if scan.get("uidvalidity")!=uidvalidity:
        scan={}
    status,rows=c.uid("search",None,"SINCE",time.strftime("%d-%b-%Y",time.localtime(time.time()-LOOKBACK_DAYS*86400)))
    all_ids=sorted({int(x) for x in (rows[0].split() if status=="OK" and rows else [])})
    cursor=int(scan.get("before_uid") or 0)
    candidates=[x for x in all_ids if not cursor or x<cursor]
    if not candidates:
        candidates=all_ids
    ids=candidates[-MAX_MESSAGES:]
    next_cursor=ids[0] if ids else 0
    fetched=[];errors=0
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
        except Exception: errors+=1
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
    observations=[]
    classification_attempts=0
    for index,compact in enumerate(new_fetched,1):
        print("TASK_CLASSIFICATION_PROGRESS="+str(index)+"/"+str(len(new_fetched)),flush=True)
        try:
            classification_attempts+=1
            d=classify(compact)
            processed.add(compact["source_ref"])
            processed_order.append(compact["source_ref"])
            if not d["actionable"] or d["status"]=="NONE":continue
            k=key(d)
            if not k:continue
            observations.append((message_time(compact.get("date")),k,d,compact))
        except Exception: errors+=1
    # Reconcile chronologically so a later completion/update wins over an older
    # request. Preserve prior state when a task is outside this bounded scan.
    tasks=dict(previous)
    for observed,k,d,msg in sorted(observations,key=lambda x:x[0]):
        task_id=resolve_task_id(d,msg,tasks)
        if not task_id:continue
        old=tasks.get(task_id,{})
        source_ids=set(old.get("source_message_ids") or [])
        if msg.get("message_id"):source_ids.add(str(msg["message_id"])[:300])
        if old and not observation_is_newer(old,observed):
            old["source_message_ids"]=sorted(source_ids)
            tasks[task_id]=old
            continue
        status=effective_status(old,d["status"])
        evidence=paperless_search(d.get("evidence_query") or d.get("topic") or d.get("title"))
        tasks[task_id]={
            "id":task_id,"identity_semantic":key(d),"thread_root_id":thread_root(msg),
            "title":str(d.get("title") or old.get("title") or "Untitled task")[:160],
            "status":status,"due_date":d.get("due_date") or old.get("due_date"),
            "counterparty":d.get("counterparty") or old.get("counterparty"),
            "topic":d.get("topic") or old.get("topic"),"source":"gmail",
            "email_message_id":str(msg.get("message_id",""))[:300],
            "source_message_ids":sorted(source_ids),
            "paperless_evidence":evidence or old.get("paperless_evidence",[]),
            "updated_from_email":str(msg.get("date",""))[:100],"observed_at":observed,
            "reason":str(d.get("reason") or "")[:300]
        }
    cutoff=int(time.time())-STALE_DAYS*86400
    tasks={k:v for k,v in tasks.items() if int(v.get("observed_at") or int(time.time()))>=cutoff or v.get("status")!="DONE"}
    open_tasks=[x for x in tasks.values() if x.get("status")!="DONE"]
    resolved=[x for x in tasks.values() if x.get("status")=="DONE"]
    open_tasks.sort(key=lambda x:(x.get("due_date") or "9999-99-99",x["title"]))
    payload={"schema":"lifeos_tasks_v3","generated_time":int(time.time()),"lookback_days":LOOKBACK_DAYS,"messages_considered":len(ids),"messages_classified":classification_attempts,"messages_reused":messages_reused,"errors":errors,"tasks":open_tasks,"resolved":resolved,"authority":{"email":"obligation/progress evidence","paperless":"document evidence","lifeos":"derived persistent task state"}}
    STATE.parent.mkdir(parents=True,exist_ok=True);OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(payload,indent=2)+"\n");tmp.replace(STATE)
    outtmp=OUT.with_suffix(".tmp");outtmp.write_text(json.dumps(payload,indent=2)+"\n");outtmp.replace(OUT)
    scan_payload={"schema":"lifeos_task_scan_v1","uidvalidity":uidvalidity,"before_uid":next_cursor,"processed_message_ids":processed_order[-10000:],"updated_time":int(time.time())}
    scan_tmp=SCAN_STATE.with_suffix(".tmp");scan_tmp.write_text(json.dumps(scan_payload,indent=2)+"\n");scan_tmp.replace(SCAN_STATE)
    print(json.dumps({"tasks":len(open_tasks),"resolved":len(resolved),"messages":len(ids),"classified":classification_attempts,"reused":messages_reused,"errors":errors}))
if __name__=="__main__":main()
