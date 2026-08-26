#!/usr/bin/env python3
from pathlib import Path
import json, time, traceback, importlib.util, sys
sys.path.insert(0, '/home/joshan/automation')
from queues.lifeos_queue_helpers import create_pa_job

HA = Path("/opt/stacks/homeassistant/config")
REQ = HA / "lifeos_ask_request.json"
ANS = HA / "lifeos_ask_answer.json"
AUDIT_FLAG = Path("/home/joshan/automation/logs/lifeos_qa_audit_required.flag")
LOOKUP = Path("/home/joshan/automation/lifeos_ask/lifeos_local_paperless_lookup.py")

last_seen = 0

def answer_question(q):
    ql = q.lower()

    # Simple known answers from current Paperless test results
    if "bike" in ql and "insurance" in ql:
        return "Bike insurance provider: Hastings Direct"

    if ("car" in ql or "ko67fjf" in ql) and "insurance" in ql:
        return "Car insurance provider: Aviva Zero"

    if "mortgage" in ql and ("who" in ql or "account" in ql or "provider" in ql):
        return "Mortgage provider: Aldermore. Account number: 109897438"

    if "mortgage" in ql and ("left" in ql or "remaining" in ql or "outstanding" in ql or "balance" in ql):
        return "Mortgage outstanding: £146,074.08"

    return "I don't know that yet. This simple mode currently answers mortgage, car insurance, and bike insurance questions only."

while True:
    try:
        if REQ.exists():
            req = json.loads(REQ.read_text())
            qtime = int(req.get("question_time", 0))
            q = req.get("question", "")

            if q and qtime > last_seen:
                last_seen = qtime
                try:
                    ans = answer_question(q)
                    out = {
                      "ok": True,
                      "status": "complete",
                      "question": q,
                      "question_time": qtime,
                      "answer": ans,
                      "answer_time": int(time.time()),
                      "route": "local_only"
                    }
                except Exception as e:
                    out = {
                      "ok": False,
                      "status": "error",
                      "question": q,
                      "question_time": qtime,
                      "answer": f"Local answer failed: {e}",
                      "answer_time": int(time.time()),
                      "route": "local_only",
                      "traceback": traceback.format_exc()
                    }

                ANS.write_text(json.dumps(out, indent=2))
                AUDIT_FLAG.write_text("1\n")
                create_pa_job("qa_audit", "low", {
                    "question_time": qtime,
                    "question": q,
                    "answer_time": out.get("answer_time", 0),
                    "answer": out.get("answer", ""),
                    "route": out.get("route", "local_only")
                })

                audit = {
                  "question_time": out.get("question_time"),
                  "question": out.get("question"),
                  "answer_time": out.get("answer_time"),
                  "answer": out.get("answer"),
                  "pa_audit_result": "",
                  "audit_required": True
                }

                audit_file = Path("/home/joshan/automation/logs/lifeos_qa_audit_table.jsonl")
                audit_file.parent.mkdir(parents=True, exist_ok=True)

                with audit_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(audit, ensure_ascii=False) + "\n")
    except Exception:
        pass

    time.sleep(1)
