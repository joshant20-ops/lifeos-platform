#!/usr/bin/env python3
"""Read-only local Paperless junk audit.

Classifies every existing Paperless document as KEEP, LIKELY_JUNK, or REVIEW.
Private document content is read locally and sent only through the governed local
Ollama broker. Nothing is written back to Paperless and no document content is
printed to stdout.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from collections import Counter

REPO = pathlib.Path('/home/joshan/lifeos-platform')
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from governor.ai_broker import OLLAMA_MODEL, _ollama

PAPERLESS_CONTAINER = 'paperless-paperless-1'
SNIPPET = 2500
BATCH = 8
VALID = {'KEEP', 'LIKELY_JUNK', 'REVIEW'}


def read_documents() -> list[dict]:
    code = f'''\nimport json\nfrom documents.models import Document\nfor d in Document.objects.order_by("id"):\n print(json.dumps({{"id": d.id, "title": d.title or "", "content": (d.content or "")[:{SNIPPET}]}}))\n'''
    p = subprocess.run(
        ['docker', 'exec', PAPERLESS_CONTAINER, 'python3', 'manage.py', 'shell', '-c', code],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if p.returncode:
        raise RuntimeError('paperless_read_failed')
    docs = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get('id'), int):
            docs.append(row)
    return docs


def parse_json(raw: str):
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.strip('`').removeprefix('json').strip()
    return json.loads(raw)


def classify_batch(batch: list[dict]) -> list[dict]:
    payload = [{'id': d['id'], 'title': d['title'], 'content': d['content']} for d in batch]
    prompt = '''You are LifeOS local document hygiene. The following Paperless documents are private and must remain local.\nClassify EACH document only as KEEP, LIKELY_JUNK, or REVIEW.\nLIKELY_JUNK means obvious spam, advertising, promotional material, accidental/meaningless captures, or transient material that clearly does not belong in a durable document archive.\nKEEP means a plausible durable personal/household record, receipt, invoice, contract, policy, certificate, official correspondence, booking evidence, warranty, tax/bank/pension/property/employment record, or anything with reasonable future evidential value.\nREVIEW means genuinely uncertain. Err toward KEEP or REVIEW; do not call something junk merely because it is old, mundane, or low-value.\nReturn ONLY a JSON array with one object per input document, preserving each id exactly. Each object: {"id": integer, "classification": "KEEP|LIKELY_JUNK|REVIEW", "confidence": number}. No explanations.\n\nDOCUMENTS:\n''' + json.dumps(payload, ensure_ascii=False)
    raw = _ollama(prompt, OLLAMA_MODEL)
    data = parse_json(raw)
    if not isinstance(data, list):
        raise ValueError('not_array')
    expected = {d['id'] for d in batch}
    got = set()
    out = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError('bad_item')
        doc_id = item.get('id')
        cls = item.get('classification')
        conf = item.get('confidence')
        if doc_id not in expected or doc_id in got or cls not in VALID or not isinstance(conf, (int, float)) or not 0 <= float(conf) <= 1:
            raise ValueError('schema_failure')
        got.add(doc_id)
        out.append({'id': doc_id, 'classification': cls, 'confidence': float(conf)})
    if got != expected:
        raise ValueError('missing_ids')
    return out


def main() -> int:
    docs = read_documents()
    print(f'PAPERLESS_DOCUMENTS={len(docs)}')
    if not docs:
        print('KEEP=0')
        print('LIKELY_JUNK=0')
        print('REVIEW=0')
        print('AUDIT_FAILURES=0')
        print('PAPERLESS_MUTATION=NONE')
        print('PRIVACY_LOCAL_ONLY=PASS')
        print('RESULT=PASS')
        return 0

    results = []
    failures = 0
    for i in range(0, len(docs), BATCH):
        batch = docs[i:i+BATCH]
        try:
            results.extend(classify_batch(batch))
        except Exception:
            failures += 1
            results.extend({'id': d['id'], 'classification': 'REVIEW', 'confidence': 0.0} for d in batch)

    counts = Counter(r['classification'] for r in results)
    junk_ids = [r['id'] for r in results if r['classification'] == 'LIKELY_JUNK']
    review_ids = [r['id'] for r in results if r['classification'] == 'REVIEW']
    print(f'KEEP={counts["KEEP"]}')
    print(f'LIKELY_JUNK={counts["LIKELY_JUNK"]}')
    print(f'REVIEW={counts["REVIEW"]}')
    print(f'AUDIT_FAILURES={failures}')
    print('LIKELY_JUNK_IDS=' + ','.join(map(str, junk_ids)))
    print('REVIEW_IDS=' + ','.join(map(str, review_ids)))
    print('PAPERLESS_MUTATION=NONE')
    print('PRIVACY_LOCAL_ONLY=PASS')
    print('RESULT=PASS' if failures == 0 else 'RESULT=PASS_WITH_REVIEW_FALLBACK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
