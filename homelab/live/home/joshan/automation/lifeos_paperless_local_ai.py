#!/usr/bin/env python3
"""Read-only Paperless -> governed local-AI bridge.

Paperless remains document authority. This bridge reads an already-ingested
Paperless document locally and asks LifeOS's Governor broker to interpret it.
It never writes back to Paperless and never sends document content to cloud AI.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path('/home/joshan/lifeos-platform')
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from governor.ai_broker import OLLAMA_MODEL, _ollama

PAPERLESS_CONTAINER = 'paperless-paperless-1'
MAX_CONTENT = 24000


def read_document(document_id: int) -> dict:
    code = f'''\nimport json\nfrom documents.models import Document\nd=Document.objects.get(pk={int(document_id)})\nprint(json.dumps({{"id": d.id, "title": d.title or "", "content": (d.content or "")[:{MAX_CONTENT}]}}))\n'''
    result = subprocess.run(
        ['docker', 'exec', PAPERLESS_CONTAINER, 'python3', 'manage.py', 'shell', '-c', code],
        check=False, capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError('paperless_read_failed')
    lines = [x.strip() for x in result.stdout.splitlines() if x.strip().startswith('{')]
    if not lines:
        raise RuntimeError('paperless_no_document_json')
    return json.loads(lines[-1])


def analyse(doc: dict) -> dict:
    prompt = '''You are LifeOS local document intelligence. The following content is private and must remain local.\nReturn ONLY JSON with keys: document_type, summary, obligations, dates, amounts, organisations, confidence.\nDo not invent facts. Unknown values must be null or empty arrays.\n\nDOCUMENT TITLE:\n''' + doc['title'] + '\n\nDOCUMENT CONTENT:\n' + doc['content']
    raw = _ollama(prompt, OLLAMA_MODEL).strip()
    if raw.startswith('```'):
        raw = raw.strip('`').removeprefix('json').strip()
    try:
        intelligence = json.loads(raw)
    except json.JSONDecodeError:
        intelligence = {'summary': raw, 'parse_status': 'non_json'}
    return {
        'status': 'ok',
        'paperless_document_id': doc['id'],
        'paperless_title': doc['title'],
        'local_ai_model': OLLAMA_MODEL,
        'privacy': 'local_only',
        'paperless_writeback_performed': False,
        'intelligence': intelligence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('document_id', type=int)
    args = parser.parse_args()
    print(json.dumps(analyse(read_document(args.document_id)), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
