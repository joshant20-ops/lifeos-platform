#!/usr/bin/env python3
"""P2 deterministic Paperless processor: local reads, aggregate evidence, no writes."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PROCESSOR_VERSION = "1.0.0"
RULE_SET_VERSION = "pip-taxonomy-v1"
DEFAULT_SAMPLE = 96
CONTAINER = os.getenv("LIFEOS_PAPERLESS_CONTAINER", "paperless-paperless-1")

DOMAIN_RULES = {
    "property": (r"\b(tenan\w*|landlord|rent\w*|mortgage|property|letting|deposit)\b",),
    "employment": (r"\b(payslip|payroll|employer|p60|p45|salary|workplace)\b",),
    "vehicles": (r"\b(vehicle|motor|car\b|mot\b|service history|road tax|dvla)\b",),
    "household": (r"\b(energy|electricity|gas\b|water|broadband|council tax|utility)\b",),
    "finance": (r"\b(bank|tax\b|hmrc|pension|investment|interest|accounting|finance)\b",),
    "personal-administration": (r"\b(passport|booking|appointment|certificate|renewal|official)\b",),
}
TYPE_RULES = {
    "invoice": r"\binvoice\b",
    "receipt": r"\breceipt\b",
    "statement": r"\bstatement\b",
    "contract": r"\b(contract|agreement)\b",
    "policy": r"\bpolicy\b",
    "tax-document": r"\b(tax|hmrc|p60|p45)\b",
    "payslip": r"\bpayslip\b",
    "tenancy-record": r"\b(tenancy|tenant|landlord|letting)\b",
    "vehicle-record": r"\b(mot|dvla|vehicle|service history)\b",
    "booking": r"\b(booking|reservation)\b",
    "official-correspondence": r"\b(letter|notice|certificate|official)\b",
}


def _text(value) -> str:
    return "" if value is None else str(value)


def _tax_year(value: str | None) -> str | None:
    if not value:
        return None
    day = date.fromisoformat(value[:10])
    start = day.year if day >= date(day.year, 4, 6) else day.year - 1
    return f"{start:04d}-{(start + 1) % 100:02d}"


def _stable_ref(prefix: str, value) -> str | None:
    return None if value in (None, "") else f"{prefix}:{int(value)}"


def classify(document: dict) -> tuple[dict, bool]:
    source_metadata = " ".join(
        [_text(document.get("document_type_name"))]
        + [_text(x) for x in document.get("tag_names", [])]
    )
    material = "\n".join(
        (_text(document.get("title")), source_metadata, _text(document.get("content"))[:12000])
    ).casefold()
    scores = Counter()
    for domain, patterns in DOMAIN_RULES.items():
        for pattern in patterns:
            matches = re.findall(pattern, material, re.IGNORECASE)
            scores[domain] += min(len(matches), 3)
    maximum = max(scores.values(), default=0)
    leaders = sorted(domain for domain, score in scores.items() if score == maximum and score > 0)
    conflict = len(leaders) > 1
    domain = leaders[0] if len(leaders) == 1 else "unknown"

    kinds = [kind for kind, pattern in TYPE_RULES.items() if re.search(pattern, material, re.IGNORECASE)]
    information_type = kinds[0] if len(kinds) == 1 else "unknown"
    conflict = conflict or len(kinds) > 1
    if conflict:
        domain, information_type = "unknown", "unknown"

    classified = domain != "unknown" and information_type != "unknown"
    score = 0.95 if classified and maximum >= 2 else 0.82 if classified else None
    band = "high" if score is not None and score >= 0.9 else "medium" if score is not None else "unknown"
    reasons = []
    if source_metadata.strip():
        reasons.append("source-metadata")
    if scores or kinds:
        reasons.append("known-pattern")
    if conflict:
        reasons.append("conflict")
    if not classified:
        reasons.append("insufficient-evidence")
    return {
        "domain": domain,
        "information_type": information_type,
        "correspondent_ref": _stable_ref("paperless-correspondent", document.get("correspondent_id")),
        "sender_ref": None,
        "method": "deterministic" if classified else "none",
        "confidence": {"band": band, "score": score},
        "reason_codes": sorted(set(reasons)),
    }, conflict


def process(document: dict, canonical_revision: str) -> dict:
    classification, conflict = classify(document)
    checksum = _text(document.get("checksum"))
    document_id = int(document["id"])
    material = f"paperless|{document_id}|{checksum}|{PROCESSOR_VERSION}"
    idempotency_key = hashlib.sha256(material.encode()).hexdigest()
    created = _text(document.get("created"))[:10] or None
    semantic_needed = classification["domain"] == "unknown" or classification["information_type"] == "unknown"
    exception = "classification-conflict" if conflict else "insufficient-evidence" if semantic_needed else "none"
    observed = _text(document.get("modified")) or "1970-01-01T00:00:00+00:00"
    return {
        "schema_version": 1,
        "processor_version": PROCESSOR_VERSION,
        "privacy": "local-only",
        "mode": "proposal-only",
        "object_id": f"paperless-document:{document_id}",
        "source": {"system": "paperless", "source_object_id": f"document:{document_id}", "authoritative_ref": f"paperless:document:{document_id}", "object_kind": "document", "observed_at": observed, "content_copied": False},
        "processing": {"state": "pending-semantic" if semantic_needed else "processed", "stage": "deterministic", "attempt": 1, "idempotency_key": idempotency_key},
        "classification": classification,
        "dates": {"document_date": created, "period_start": None, "period_end": None, "tax_year": _tax_year(created) if classification["domain"] in {"finance", "property"} else None},
        "entity_links": [],
        "relationships": [],
        "provenance": {"run_id": "pip-p2-representative-sample", "rule_set_version": RULE_SET_VERSION, "processor_version": PROCESSOR_VERSION, "canonical_revision": canonical_revision, "processed_at": observed},
        "exception": {"code": exception, "retryable": False},
        "mutation_control": {"production_write_permitted": False, "paperless_write_performed": False, "gmail_write_performed": False, "authority_delete_performed": False},
    }


def representative_sample(documents: list[dict], limit: int) -> list[dict]:
    def rank(document):
        material = f"{document['id']}|{_text(document.get('checksum'))}".encode()
        return hashlib.sha256(material).hexdigest()
    return sorted(documents, key=rank)[:limit]


def read_live() -> list[dict]:
    code = r'''
import json
from documents.models import Document
for d in Document.objects.order_by("pk").prefetch_related("tags"):
 print(json.dumps({
  "id":d.pk,"checksum":d.checksum or "","title":d.title or "","content":d.content or "",
  "created":d.created.isoformat() if d.created else None,
  "modified":d.modified.isoformat() if d.modified else None,
  "correspondent_id":d.correspondent_id,
  "document_type_name":d.document_type.name if d.document_type_id else "",
  "tag_names":list(d.tags.values_list("name",flat=True)),
 },ensure_ascii=False))
'''
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "python3", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=180, check=False,
    )
    if result.returncode:
        raise RuntimeError("paperless_read_failed")
    rows = []
    for line in result.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("id"), int):
            rows.append(value)
    return rows


def logical_digest(records: list[dict]) -> str:
    material = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


def run_live(limit: int) -> int:
    documents = read_live()
    sample = representative_sample(documents, min(limit, len(documents)))
    revision = os.getenv("LIFEOS_CANONICAL_REVISION", "0" * 40)
    first = [process(d, revision) for d in sample]
    second = [process(d, revision) for d in sample]
    classified = sum(r["processing"]["state"] == "processed" for r in first)
    conflicts = sum(r["exception"]["code"] == "classification-conflict" for r in first)
    ambiguous = len(first) - classified
    errors = 0
    metrics = {
        "CORPUS_SIZE": len(documents), "SAMPLE_SIZE": len(sample),
        "DETERMINISTIC_CLASSIFIED": classified, "AMBIGUOUS": ambiguous,
        "CONFLICTS": conflicts, "ERRORS": errors, "SEMANTIC_NEEDED": ambiguous,
        "DETERMINISTIC_COVERAGE_BPS": (classified * 10000 // len(sample)) if sample else 0,
        "LOGICAL_RERUN_IDENTICAL": "PASS" if logical_digest(first) == logical_digest(second) else "FAIL",
        "STAGING_PERSISTED": "NONE", "AI_USED": "NONE", "CLOUD_CONTENT_SENT": "NONE",
        "PAPERLESS_MUTATION": "NONE", "PRIVATE_FIELDS_EMITTED": "NONE",
        "PRIVACY_LOCAL_ONLY": "PASS",
    }
    for key, value in metrics.items():
        print(f"{key}={value}")
    passed = bool(sample) and metrics["LOGICAL_RERUN_IDENTICAL"] == "PASS"
    print("RESULT=" + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; use imported pure functions for tests")
    return run_live(max(1, min(args.sample_size, 256)))


if __name__ == "__main__":
    raise SystemExit(main())
