#!/usr/bin/env python3
"""LifeOS personal task reconciler.

Reads recent Gmail locally, extracts user obligations with governed local AI, and
reconciles them against Paperless evidence. Private content never leaves the host.
The published HA JSON contains only user-facing task summaries plus stable provenance.
"""
from __future__ import annotations
import email, imaplib, json, os, re, ssl, sys, time
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
MAX_MESSAGES=int(os.getenv("LIFEOS_TASK_EMAIL_LIMIT","150"))
LOOKBACK_DAYS=int(os.getenv("LIFEOS_TASK_LOOKBACK_DAYS","90"))

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

def classify(msg):
    compact={"from":str(msg.get("From",""))[:300],"subject":str(msg.get("Subject",""))[:500],"date":str(msg.get("Date",""))[:100],"body":text_of(msg)}
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

def main():
    user=secret("LIFEOS_IMAP_USER",("gmail-imap-user","imap-user","gmail-user"))
    password=secret("LIFEOS_IMAP_PASSWORD",("gmail-imap-password","imap-password","gmail-app-password"))
    c=imaplib.IMAP4_SSL(os.getenv("LIFEOS_IMAP_HOST","imap.gmail.com"),int(os.getenv("LIFEOS_IMAP_PORT","993")),ssl_context=ssl.create_default_context())
    c.login(user,password);c.select("INBOX",readonly=True)
    status,rows=c.search(None,"SINCE",time.strftime("%d-%b-%Y",time.localtime(time.time()-LOOKBACK_DAYS*86400)))
    ids=(rows[0].split() if status=="OK" and rows else [])[-MAX_MESSAGES:]
    tasks={}
    errors=0
    for uid in ids:
        try:
            st,data=c.fetch(uid,"(RFC822)")
            if st!="OK":continue
            raw=next(x[1] for x in data if isinstance(x,tuple));msg=email.message_from_bytes(raw)
            d=classify(msg)
            if not d["actionable"] or d["status"]=="NONE":continue
            k=key(d)
            if not k:continue
            evidence=paperless_search(d.get("evidence_query") or d.get("topic") or d.get("title"))
            item={"id":k,"title":str(d.get("title") or "Untitled task")[:160],"status":d["status"],"due_date":d.get("due_date"),"counterparty":d.get("counterparty"),"topic":d.get("topic"),"source":"gmail","email_message_id":str(msg.get("Message-ID",""))[:300],"paperless_evidence":evidence,"updated_from_email":str(msg.get("Date",""))[:100]}
            tasks[k]=item
        except Exception: errors+=1
    c.logout()
    open_tasks=[x for x in tasks.values() if x["status"]!="DONE"]
    open_tasks.sort(key=lambda x:(x.get("due_date") or "9999-99-99",x["title"]))
    payload={"schema":"lifeos_tasks_v2","generated_time":int(time.time()),"lookback_days":LOOKBACK_DAYS,"messages_considered":len(ids),"errors":errors,"tasks":open_tasks,"resolved":[x for x in tasks.values() if x["status"]=="DONE"],"authority":{"email":"obligation/progress evidence","paperless":"document evidence","lifeos":"derived task state"}}
    STATE.parent.mkdir(parents=True,exist_ok=True);OUT.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(payload,indent=2)+"\n");OUT.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps({"tasks":len(open_tasks),"resolved":len(payload["resolved"]),"messages":len(ids),"errors":errors}))
if __name__=="__main__":main()
