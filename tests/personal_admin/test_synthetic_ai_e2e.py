#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path

REPO = Path.home() / "lifeos-platform"
sys.path.insert(0, str(REPO))

from governor import ai_broker


SYNTHETIC_INPUT = """
This is SYNTHETIC TEST DATA only.

Email:
From: appointments@example.invalid
Subject: Appointment confirmation

Your appointment is on 15 October 2099 at 14:00.
Please arrive 10 minutes early.
Bring your insurance certificate.
If you cannot attend, cancel at least 48 hours beforehand.

Calendar:
No existing appointment.

Paperless:
Document reference SYNTHETIC-PAPERLESS-0001
Title: Insurance Certificate
Valid until 31 December 2099.
"""


PROMPT = f"""
You are the local LifeOS Personal Administration reasoning engine.

Analyse the synthetic information below.

Return ONLY one JSON object with this exact structure:

{{
  "event": {{
    "title": "",
    "date": "",
    "time": ""
  }},
  "obligations": [
    {{
      "description": "",
      "due": ""
    }}
  ],
  "actions": [
    {{
      "description": "",
      "due": ""
    }}
  ],
  "evidence": [
    {{
      "document_ref": "",
      "reason": ""
    }}
  ],
  "attention_required": true,
  "summary": ""
}}

Rules:
- Do not invent information.
- Associate relevant Paperless evidence.
- Extract obligations and actionable deadlines.
- Dates must use YYYY-MM-DD where possible.
- Times must use HH:MM.
- This is synthetic data.
- Do not attempt any external action.

INPUT:

{SYNTHETIC_INPUT}
"""


def extract_json(raw: str):
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")

    if start >= 0 and end > start:
        return json.loads(raw[start:end + 1])

    raise ValueError("No valid JSON object found")


print("=== LIFEOS SYNTHETIC PA AI TEST ===")
print("MODEL=" + str(ai_broker.OLLAMA_MODEL))

raw = ai_broker._ollama(PROMPT, ai_broker.OLLAMA_MODEL)

print("RAW_RESPONSE=" + repr(raw))

try:
    result = extract_json(raw)
except Exception as e:
    print("JSON_PARSE=FAIL")
    print("ERROR=" + repr(e))
    raise SystemExit(1)

print("JSON_PARSE=PASS")

failures = []

event = result.get("event", {})

if event.get("date") != "2099-10-15":
    failures.append("event date")

if event.get("time") != "14:00":
    failures.append("event time")

obligations = result.get("obligations", [])
actions = result.get("actions", [])
evidence = result.get("evidence", [])

text_obligations = json.dumps(obligations).lower()
text_actions = json.dumps(actions).lower()
text_evidence = json.dumps(evidence).lower()

if "insurance" not in text_obligations and "insurance" not in text_actions:
    failures.append("insurance requirement")

# Accept either the original 48-hour wording or the correctly derived
# cancellation deadline of 2099-10-13.
if (
    "48" not in text_obligations
    and "48" not in text_actions
    and "2099-10-13" not in text_obligations
    and "2099-10-13" not in text_actions
):
    failures.append("48-hour cancellation rule")

if "synthetic-paperless-0001" not in text_evidence:
    failures.append("Paperless evidence association")

if result.get("attention_required") is not True:
    failures.append("attention_required")

print()
print("=== INTERPRETED RESULT ===")
print(json.dumps(result, indent=2))

print()
print("=== ACCEPTANCE ===")

if failures:
    for failure in failures:
        print("FAIL:", failure)

    print("RESULT=FAIL")
    raise SystemExit(1)

print("EVENT_EXTRACTION=PASS")
print("OBLIGATION_EXTRACTION=PASS")
print("ACTION_EXTRACTION=PASS")
print("EVIDENCE_ASSOCIATION=PASS")
print("STRUCTURED_OUTPUT=PASS")
print("RESULT=PASS")
