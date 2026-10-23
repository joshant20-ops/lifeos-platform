#!/usr/bin/env python3
"""Read-only Pi acceptance of private EmailOps previews in authenticated HA."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = Path('/home/joshan/lifeos-platform')
HA = Path('/opt/stacks/homeassistant/config')
REPORT = Path('/home/joshan/.local/share/lifeos/emailops-shadow/shadow-report.json')
TASK_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,119}')
MAX_BYTES = 2 * 1024 * 1024


class AuditFailure(Exception):
    pass


def require(ok, code):
    if not ok:
        raise AuditFailure(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(path, token=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    request = Request('http://127.0.0.1:8123' + path, headers=headers)
    opener = build_opener(NoRedirect())
    try:
        response = opener.open(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(MAX_BYTES + 1)
        require(len(body) <= MAX_BYTES, 'response_too_large')
        return response.code, response.headers, body


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_preview(payload):
    return {
        'schema': 'lifeos_emailops_shadow_task_v1', 'task_id': payload['task_id'], 'mode': 'shadow',
        'summary': str(payload.get('summary') or '')[:4000],
        'proposals': [{'title': str(p.get('title') or '')[:300], 'due_date': p.get('due_date')}
                      for p in payload.get('proposals', [])[:20] if isinstance(p, dict)],
    }


def audit(token, fetcher=fetch):
    status, _, _ = fetcher('/api/', token)
    require(status == 200, 'ha_credential_rejected' if status in {401, 403} else 'ha_api_unavailable')
    component = Path('custom_components/lifeos_pa_review/__init__.py')
    require(digest(HA / component) == digest(REPO / 'homelab/live/opt/stacks/homeassistant/config' / component),
            'component_source_mismatch')
    card = Path('www/lifeos-pa-task-card.js')
    source_card = REPO / 'homeassistant' / card
    require(digest(HA / card) == digest(source_card), 'card_source_mismatch')
    status, _, body = fetcher('/local/lifeos-pa-task-card.js')
    require(status == 200 and hashlib.sha256(body).hexdigest() == digest(source_card), 'served_card_mismatch')

    report = json.loads(REPORT.read_text())
    generated = int(report.get('generated_at') or 0)
    require(report.get('schema') == 'lifeos_emailops_comparison_v1'
            and report.get('mode') == 'shadow' and 0 <= time.time() - generated < 86400,
            'report_not_fresh')
    task_ids = {task_id for result in report['results'] for task_id in result['matched_task_ids']}
    require(bool(task_ids) and len(task_ids) <= 600, 'matched_tasks_invalid')
    checked = 0
    for task_id in sorted(task_ids):
        require(isinstance(task_id, str) and TASK_ID.fullmatch(task_id), 'task_id_invalid')
        preview = HA / 'lifeos-pa-state/emailops-shadow' / (task_id + '.json')
        require(not preview.is_symlink() and preview.stat().st_mode & 0o077 == 0, 'preview_not_private')
        payload = json.loads(preview.read_text())
        require(payload.get('schema') == 'lifeos_emailops_shadow_task_v1'
                and payload.get('task_id') == task_id and payload.get('generated_at') == generated,
                'preview_report_mismatch')
        path = '/api/lifeos_emailops_shadow/' + task_id
        status, _, _ = fetcher(path)
        require(status in {401, 403}, 'anonymous_preview_not_denied')
        status, headers, body = fetcher(path, token)
        require(status != 404, 'authenticated_preview_not_found')
        require(status == 200, 'authenticated_preview_unavailable')
        require('no-store' in headers.get('Cache-Control', '') and 'private' in headers.get('Cache-Control', ''),
                'preview_cache_policy_invalid')
        require(json.loads(body) == expected_preview(payload), 'served_preview_mismatch')
        checked += 1
    return checked


def main():
    try:
        require(platform.node() == 'Docker' and os.geteuid() == 0 and not sys.argv[1:], 'wrong_runtime')
        token = os.environ.get('HA_TOKEN', '')
        require(bool(token), 'ha_credential_missing')
        count = audit(token)
        print('EMAILOPS_REVIEW_TASKS=' + str(count))
        print('EMAILOPS_REVIEW_AUTH=PASS')
        print('EMAILOPS_REVIEW_SERVED=PASS')
        return 0
    except Exception as error:
        # Never log a URL, task identity, credential, API body or native error.
        print('EMAILOPS_REVIEW_SERVED=FAIL')
        print('EMAILOPS_REVIEW_REASON=' + (str(error) if isinstance(error, AuditFailure) else 'audit_unavailable'))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
