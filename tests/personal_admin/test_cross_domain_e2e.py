#!/usr/bin/env python3
"""Synthetic PA contract test with explicit adapter-boundary evidence."""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path("/home/joshan/lifeos-platform")
sys.path.insert(0, str(REPO))

from governor import ai_broker

PA = "/home/joshan/automation/pa_request.sh"
CAL = "/home/joshan/automation/lifeos_calendar_adapter.py"
EXPECTED_DATE = "2099-10-15"
EXPECTED_TIME = "14:00"


def email_adapter_fixture():
    return {
        "boundary": "email_adapter",
        "fixture": True,
        "subject": "Synthetic Appointment",
        "body": (
            "Your appointment is on 15 October 2099 at 14:00. "
            "Please arrive 10 minutes early. Bring your insurance certificate. "
            "If you cannot attend, cancel at least 48 hours beforehand."
        ),
    }


def paperless_adapter_fixture():
    return {
        "boundary": "paperless_adapter",
        "fixture": True,
        "document_ref": "SYNTHETIC-PAPERLESS-0001",
        "description": "Insurance certificate valid through 31 December 2099.",
    }


def canonical_date(value):
    text = str(value or "").strip()
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        year, month, day = map(int, match.groups())
        return datetime(year, month, day).date().isoformat()
    for pattern in ("%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    return None


def canonical_time(value):
    match = re.search(
        r"\b(\d{1,2}):(\d{2})(?:\s*([ap])\.?m\.?)?\b",
        str(value or ""),
        re.I,
    )
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    marker = (match.group(3) or "").lower()
    if marker == "p" and hour < 12:
        hour += 12
    elif marker == "a" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


email = email_adapter_fixture()
paperless = paperless_adapter_fixture()
prompt = f"""
This is synthetic test data only.

EMAIL ADAPTER FIXTURE:
{json.dumps(email, sort_keys=True)}

PAPERLESS ADAPTER FIXTURE:
{json.dumps(paperless, sort_keys=True)}

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

def parse_response(raw):
    text = str(raw).strip()
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        assert start >= 0 and end > start
        return json.loads(text[start : end + 1])


def validation_failures(value):
    event = value.get("event") or {}
    failures = []
    if canonical_date(event.get("date")) != EXPECTED_DATE:
        failures.append("event.date must identify 2099-10-15")
    if canonical_time(event.get("time")) != EXPECTED_TIME:
        failures.append("event.time must identify 14:00")
    if paperless["document_ref"] not in json.dumps(value.get("evidence", []), sort_keys=True):
        failures.append("evidence must contain exact document_ref " + paperless["document_ref"])
    return failures


data = None
failures = []
attempt_prompt = prompt
for attempt in range(2):
    data = parse_response(ai_broker._ollama(attempt_prompt, ai_broker.OLLAMA_MODEL))
    failures = validation_failures(data)
    if not failures:
        break
    attempt_prompt = prompt + "\nYour previous JSON failed these required checks:\n- " + "\n- ".join(failures) + "\nReturn a corrected complete JSON object only."

assert not failures, failures
print("AI_SEMANTICS=PASS")
print("EMAIL_ADAPTER_BOUNDARY=FIXTURE")
print("PAPERLESS_ADAPTER_BOUNDARY=FIXTURE")

cp = subprocess.run([PA, prompt], text=True, capture_output=True, timeout=180)
assert cp.returncode == 0, cp.stderr
result = json.loads(cp.stdout)
assert result.get("ok") is True
assert result.get("route") == "local_ai_broker"
print("PA_ROUTE=PASS")

cp = subprocess.run([sys.executable, CAL, "test"], text=True, capture_output=True, timeout=60)
assert cp.returncode == 0, cp.stdout + cp.stderr
assert "CREATE=PASS" in cp.stdout
assert "DELETE=PASS" in cp.stdout
print("CALENDAR_ADAPTER_BOUNDARY=LIVE_SYNTHETIC_CREATE_DELETE")
print("CROSS_DOMAIN_CONTRACT=PASS")
