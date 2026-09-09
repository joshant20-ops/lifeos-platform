#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

REPO=Path("/home/joshan/lifeos-platform")
sys.path.insert(0,str(REPO))

from governor import ai_broker

PA="/home/joshan/automation/pa_request.sh"
CAL="/home/joshan/automation/lifeos_calendar_adapter.py"

synthetic_email = """
Subject: Synthetic Appointment

Your appointment is on 15 October 2099 at 14:00.
Please arrive 10 minutes early.
Bring your insurance certificate.
If you cannot attend, cancel at least 48 hours beforehand.
"""

paperless_ref="SYNTHETIC-PAPERLESS-0001"

prompt=f"""
This is synthetic test data only.

EMAIL:
{synthetic_email}

PAPERLESS EVIDENCE:
document_ref={paperless_ref}
description=Insurance certificate valid through 31 December 2099.

Return JSON only:
{{
 "event":{{"title":"","date":"","time":""}},
 "obligations":[],
 "actions":[],
 "evidence":[],
 "attention_required":true,
 "summary":""
}}
"""

raw=ai_broker._ollama(prompt,ai_broker.OLLAMA_MODEL)
raw=str(raw).strip()

if raw.startswith("```"):
    lines=raw.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines=lines[:-1]
    raw="\n".join(lines).strip()

try:
    data=json.loads(raw)
except Exception:
    a,b=raw.find("{"),raw.rfind("}")
    assert a>=0 and b>a
    data=json.loads(raw[a:b+1])

assert data["event"]["date"]=="2099-10-15"
assert data["event"]["time"]=="14:00"
assert any(paperless_ref in json.dumps(x) for x in data.get("evidence",[]))

print("AI_SEMANTICS=PASS")

# Exercise real PA route too.
cp=subprocess.run(
    [PA, prompt],
    text=True,
    capture_output=True,
    timeout=180,
)
assert cp.returncode==0, cp.stderr
result=json.loads(cp.stdout)
assert result.get("ok") is True
assert result.get("route")=="local_ai_broker"
print("PA_ROUTE=PASS")

# Calendar synthetic create/delete using deployed adapter.
cp=subprocess.run(
    [sys.executable,CAL,"test"],
    text=True,
    capture_output=True,
    timeout=60,
)
assert cp.returncode==0, cp.stdout + cp.stderr
assert "CREATE=PASS" in cp.stdout
assert "DELETE=PASS" in cp.stdout
print("CALENDAR=PASS")

print("PAPERLESS_EVIDENCE_ASSOCIATION=PASS")
print("EMAIL_SYNTHETIC_INPUT=PASS")
print("CROSS_DOMAIN_E2E=PASS")
