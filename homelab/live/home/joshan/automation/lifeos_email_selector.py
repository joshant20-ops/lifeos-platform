#!/usr/bin/env python3
"""Bounded Gmail classification for selective Paperless archiving and delivery tracking.

This module does not mutate Gmail or Paperless. It accepts a small email envelope/body
snapshot, applies deterministic rules first, and asks the governed local Ollama broker
only when the decision is ambiguous. AI output is schema-validated and fails closed to
REVIEW.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Any

REPO = pathlib.Path('/home/joshan/lifeos-platform')
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from governor.ai_broker import OLLAMA_MODEL, _ollama

ARCHIVE_VALUES = {'YES', 'NO', 'REVIEW'}
DELIVERY_VALUES = {'YES', 'NO'}
DELIVERY_STATUSES = {'ORDERED', 'DISPATCHED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'UNKNOWN'}
MAX_BODY = 8000
MIN_AI_CONFIDENCE = 0.80

JUNK_PATTERNS = [
    r'\bunsubscribe\b', r'\bnewsletter\b', r'\bpromo(?:tion)?\b', r'\bsale ends\b',
    r'\bone[- ]time (?:password|passcode)\b', r'\botp\b', r'\bverification code\b',
    r'\bsocial notification\b',
]
ARCHIVE_PATTERNS = [
    r'\binvoice\b', r'\breceipt\b', r'\bpolicy document\b', r'\binsurance certificate\b',
    r'\bcontract\b', r'\bagreement\b', r'\bpayslip\b', r'\btax (?:statement|document|certificate)\b',
    r'\bwarranty\b', r'\btenancy\b', r'\bcertificate\b',
]
DELIVERY_PATTERNS = [
    r'\bdispatched\b', r'\bshipped\b', r'\bout for delivery\b', r'\bdelivered\b',
    r'\btracking (?:number|reference|id)\b', r'\byour parcel\b', r'\byour package\b',
]


def _text(email: dict[str, Any]) -> str:
    attachments = ' '.join(str(x) for x in email.get('attachments', []) or [])
    return ' '.join([
        str(email.get('from', '')),
        str(email.get('subject', '')),
        str(email.get('body', ''))[:MAX_BODY],
        attachments,
    ]).lower()


def _match_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def deterministic(email: dict[str, Any]) -> dict[str, Any] | None:
    text = _text(email)
    delivery = 'YES' if _match_any(DELIVERY_PATTERNS, text) else 'NO'

    if _match_any(JUNK_PATTERNS, text) and delivery == 'NO':
        return {'archive': 'NO', 'delivery': 'NO', 'confidence': 0.99, 'reason': 'deterministic_junk'}

    if _match_any(ARCHIVE_PATTERNS, text):
        return {'archive': 'YES', 'delivery': delivery, 'confidence': 0.98, 'reason': 'deterministic_archive'}

    if delivery == 'YES':
        return {
            'archive': 'NO', 'delivery': 'YES', 'confidence': 0.95,
            'reason': 'deterministic_delivery', 'delivery_details': extract_delivery_details(email),
        }
    return None


def extract_delivery_details(email: dict[str, Any]) -> dict[str, Any]:
    text = _text(email)
    status = 'UNKNOWN'
    for pattern, candidate in [
        (r'\bdelivered\b', 'DELIVERED'),
        (r'\bout for delivery\b', 'OUT_FOR_DELIVERY'),
        (r'\bin transit\b', 'IN_TRANSIT'),
        (r'\b(?:dispatched|shipped)\b', 'DISPATCHED'),
        (r'\border(?:ed| confirmed)\b', 'ORDERED'),
    ]:
        if re.search(pattern, text, re.I):
            status = candidate
            break
    tracking = None
    m = re.search(r'(?:tracking (?:number|reference|id)|tracking)\s*[:#-]?\s*([A-Z0-9-]{6,32})', text, re.I)
    if m:
        tracking = m.group(1)
    return {
        'merchant': None,
        'carrier': None,
        'tracking_reference': tracking,
        'expected_date': None,
        'status': status,
    }


def _normalise_ai(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.strip('`').removeprefix('json').strip()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return {'archive': 'REVIEW', 'delivery': 'NO', 'confidence': 0.0, 'reason': 'ai_non_json'}

    archive = str(d.get('archive', '')).upper()
    delivery = str(d.get('delivery', '')).upper()
    try:
        confidence = float(d.get('confidence', 0))
    except (TypeError, ValueError):
        confidence = 0.0

    if archive not in ARCHIVE_VALUES or delivery not in DELIVERY_VALUES or not (0 <= confidence <= 1):
        return {'archive': 'REVIEW', 'delivery': 'NO', 'confidence': 0.0, 'reason': 'ai_schema_invalid'}
    if confidence < MIN_AI_CONFIDENCE:
        return {'archive': 'REVIEW', 'delivery': delivery, 'confidence': confidence, 'reason': 'ai_low_confidence'}

    out: dict[str, Any] = {
        'archive': archive,
        'delivery': delivery,
        'confidence': confidence,
        'reason': str(d.get('reason', 'ai_classified'))[:200],
    }
    if delivery == 'YES':
        details = d.get('delivery_details') if isinstance(d.get('delivery_details'), dict) else {}
        status = str(details.get('status', 'UNKNOWN')).upper()
        if status not in DELIVERY_STATUSES:
            status = 'UNKNOWN'
        out['delivery_details'] = {
            'merchant': details.get('merchant'),
            'carrier': details.get('carrier'),
            'tracking_reference': details.get('tracking_reference'),
            'expected_date': details.get('expected_date'),
            'status': status,
        }
    return out


def classify(email: dict[str, Any], *, allow_ai: bool = True) -> dict[str, Any]:
    first = deterministic(email)
    if first is not None:
        first['classifier'] = 'deterministic'
        return first
    if not allow_ai:
        return {'archive': 'REVIEW', 'delivery': 'NO', 'confidence': 0.0, 'reason': 'ai_disabled', 'classifier': 'none'}

    compact = {
        'from': str(email.get('from', ''))[:300],
        'subject': str(email.get('subject', ''))[:500],
        'body': str(email.get('body', ''))[:MAX_BODY],
        'attachments': list(email.get('attachments', []) or [])[:20],
    }
    prompt = '''You are LifeOS local email triage. Private email content must remain local.\nClassify whether this email is worth durable archiving in Paperless and whether it is a delivery-tracking email.\nArchive YES only for durable evidence such as invoices, receipts, contracts, policies, certificates, tax/payslip/property/warranty documents, or other records likely to matter later.\nDo NOT archive ordinary marketing, newsletters, OTPs, routine status mail, or transient delivery updates.\nDelivery YES only for an order/parcel delivery state. Returns/refunds are OUT OF SCOPE.\nReturn ONLY JSON with: archive (YES|NO|REVIEW), delivery (YES|NO), confidence (0..1), reason, and optional delivery_details {merchant,carrier,tracking_reference,expected_date,status}.\nAllowed delivery status: ORDERED, DISPATCHED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, UNKNOWN.\nDo not invent facts.\n\nEMAIL:\n''' + json.dumps(compact, ensure_ascii=False)
    result = _normalise_ai(_ollama(prompt, OLLAMA_MODEL))
    result['classifier'] = 'local_ai'
    return result


def main() -> int:
    email = json.load(sys.stdin)
    print(json.dumps(classify(email), indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
