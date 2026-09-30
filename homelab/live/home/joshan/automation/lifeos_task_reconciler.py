#!/usr/bin/env python3
"""LifeOS personal task reconciler.

Reads recent Gmail locally, extracts user obligations with governed local AI, and
reconciles them against Paperless evidence. Private content never leaves the host.
The published HA JSON contains only user-facing task summaries plus stable provenance.
"""
from __future__ import annotations
import email, imaplib, json, os, re, ssl, sys, time
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
OUT=HA/"www/lifeos_tasks.json"
MAX_MESSAGES=int(os.getenv("LIFEOS_TASK_EMAIL_LIMIT","40"))
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

def load_previous():
    try:
        data=json.loads(STATE.read_text())
        rows=(data.get("tasks") or [])+(data.get("resolved") or [])
        return {str(x.get("id")):x for x in rows if isinstance(x,dict) and x.get("id")}
    except Exception:return {}

def message_time(date_value):
    try:return int(parsedate_to_datetime(str(date_value or "")).timestamp())
    except Exception:return int(time.time())

def main():
    previous=load_previous()
    user=secret("LIFEOS_IMAP_USER",("gmail-imap-user","imap-user","gmail-user"))
    password=secret("LIFEOS_IMAP_PASSWORD",("gmail-imap-password","imap-password","gmail-app-password"))
    c=imaplib.IMAP4_SSL(os.getenv("LIFEOS_IMAP_HOST","imap.gmail.com"),int(os.getenv("LIFEOS_IMAP_PORT","993")),ssl_context=ssl.create_default_context())
    c.login(user,password);c.select("INBOX",readonly=True)
    status,rows=c.search(None,"SINCE",time.strftime("%d-%b-%Y",time.localtime(time.time()-LOOKBACK_DAYS*86400)))
    ids=(rows[0].split() if status=="OK" and rows else [])[-MAX_MESSAGES:]
    fetched=[];errors=0
    for uid in ids:
        try:
            st,data=c.fetch(uid,"(RFC822)")
            if st!="OK":continue
            raw=next(x[1] for x in data if isinstance(x,tuple));msg=email.message_from_bytes(raw)
            fetched.append({
                "from":str(msg.get("From",""))[:300],
                "subject":str(msg.get("Subject",""))[:500],
                "date":str(msg.get("Date",""))[:100],
                "message_id":str(msg.get("Message-ID",""))[:300],
                "body":text_of(msg),
            })
        except Exception: errors+=1
    try:
        c.logout()
    except Exception:
        pass

    # Keep the network mailbox session out of the slow local inference loop.
    observations=[]
    for compact in fetched:
        try:
            d=classify(compact)
            if not d["actionable"] or d["status"]=="NONE":continue
            k=key(d)
            if not k:continue
            observations.append((message_time(compact.get("date")),k,d,compact))
        except Exception: errors+=1
    # Reconcile chronologically so a later completion/update wins over an older
    # request. Preserve prior state when a task is outside this bounded scan.
    tasks=dict(previous)
    for observed,k,d,msg in sorted(observations,key=lambda x:x[0]):
        evidence=paperless_search(d.get("evidence_query") or d.get("topic") or d.get("title"))
        old=tasks.get(k,{})
        tasks[k]={
            "id":k,"title":str(d.get("title") or old.get("title") or "Untitled task")[:160],
            "status":d["status"],"due_date":d.get("due_date") or old.get("due_date"),
            "counterparty":d.get("counterparty") or old.get("counterparty"),
            "topic":d.get("topic") or old.get("topic"),"source":"gmail",
            "email_message_id":str(compact.get("message_id",""))[:300],
            "paperless_evidence":evidence or old.get("paperless_evidence",[]),
            "updated_from_email":str(compact.get("date",""))[:100],"observed_at":observed,
            "reason":str(d.get("reason") or "")[:300]
        }
    cutoff=int(time.time())-STALE_DAYS*86400
    tasks={k:v for k,v in tasks.items() if int(v.get("observed_at") or int(time.time()))>=cutoff or v.get("status")!="DONE"}
    open_tasks=[x for x in tasks.values() if x.get("status")!="DONE"]
    resolved=[x for x in tasks.values() if x.get("status")=="DONE"]
    open_tasks.sort(key=lambda x:(x.get("due_date") or "9999-99-99",x["title"]))
    payload={"schema":"lifeos_tasks_v3","generated_time":int(time.time()),"lookback_days":LOOKBACK_DAYS,"messages_considered":len(ids),"errors":errors,"tasks":open_tasks,"resolved":resolved,"authority":{"email":"obligation/progress evidence","paperless":"document evidence","lifeos":"derived persistent task state"}}
    STATE.parent.mkdir(parents=True,exist_ok=True);OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(payload,indent=2)+"\n");tmp.replace(STATE)
    outtmp=OUT.with_suffix(".tmp");outtmp.write_text(json.dumps(payload,indent=2)+"\n");outtmp.replace(OUT)
    print(json.dumps({"tasks":len(open_tasks),"resolved":len(resolved),"messages":len(ids),"errors":errors}))
if __name__=="__main__":main()
