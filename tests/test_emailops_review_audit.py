"""Synthetic contracts for read-only served EmailOps review acceptance."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from governor import emailops_review_audit as audit


class EmailOpsReviewAuditTests(unittest.TestCase):
    def test_real_served_contract_requires_auth_exact_payload_and_private_cache(self):
        import time
        for fault, expected in (
            (None, None), ('component', 'component_source_mismatch'),
            ('card', 'served_card_mismatch'), ('anonymous', 'anonymous_preview_not_denied'),
            ('credential', 'ha_credential_rejected'), ('auth', 'preview_route_not_loaded'), ('cache', 'preview_cache_policy_invalid'),
            ('body', 'served_preview_mismatch'), ('mode', 'preview_not_private'),
            ('stale', 'report_not_fresh'),
        ):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo, ha = root / 'repo', root / 'ha'
                component = 'custom_components/lifeos_pa_review/__init__.py'
                for base, path in ((ha, component), (repo / 'homelab/live/opt/stacks/homeassistant/config', component),
                                   (ha, 'www/lifeos-pa-task-card.js'), (repo / 'homeassistant', 'www/lifeos-pa-task-card.js')):
                    target = base / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('fixture')
                if fault == 'component':
                    (ha / component).write_text('old')
                generated = int(time.time()) - (90000 if fault == 'stale' else 0)
                report = root / 'report.json'
                report.write_text(json.dumps({'schema': 'lifeos_emailops_comparison_v1', 'mode': 'shadow',
                    'generated_at': generated, 'results': [{'matched_task_ids': ['synthetic-task']}]}))
                preview = ha / 'lifeos-pa-state/emailops-shadow/synthetic-task.json'
                preview.parent.mkdir(parents=True)
                payload = {'schema': 'lifeos_emailops_shadow_task_v1', 'task_id': 'synthetic-task',
                           'generated_at': generated, 'summary': 'PRIVATE_SENTINEL', 'proposals': []}
                preview.write_text(json.dumps(payload))
                preview.chmod(0o644 if fault == 'mode' else 0o600)
                calls = []
                def fetcher(path, token=None):
                    calls.append((path, token))
                    if path == '/api/':
                        return (401 if fault == 'credential' else 200), {}, b'{}'
                    if path.startswith('/local/'):
                        return 200, {}, b'wrong' if fault == 'card' else b'fixture'
                    if token is None:
                        return (200 if fault == 'anonymous' else 401), {}, b''
                    self.assertEqual(token, 'secret-fixture')
                    body = {} if fault == 'body' else audit.expected_preview(payload)
                    return (404 if fault == 'auth' else 200), {'Cache-Control': '' if fault == 'cache' else 'no-store, private'}, json.dumps(body).encode()
                with patch.object(audit, 'REPO', repo), patch.object(audit, 'HA', ha), patch.object(audit, 'REPORT', report):
                    if expected:
                        with self.assertRaisesRegex(audit.AuditFailure, '^' + expected + '$'):
                            audit.audit('secret-fixture', fetcher)
                    else:
                        self.assertEqual(audit.audit('secret-fixture', fetcher), 1)
                        self.assertEqual([token for _, token in calls], ['secret-fixture', None, None, 'secret-fixture'])

    def test_redirects_are_not_followed_with_a_credential(self):
        self.assertIsNone(audit.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.test'))

    def test_unexpected_errors_never_expose_private_content(self):
        output = io.StringIO()
        with patch.object(audit.platform, 'node', return_value='Docker'), patch.object(audit.os, 'geteuid', return_value=0), \
             patch.object(audit.sys, 'argv', ['audit']), patch.dict(audit.os.environ, {'HA_TOKEN': 'secret-fixture'}), \
             patch.object(audit, 'audit', side_effect=ValueError('PRIVATE_SENTINEL')), redirect_stdout(output):
            self.assertEqual(audit.main(), 1)
        self.assertNotIn('PRIVATE_SENTINEL', output.getvalue())
        self.assertNotIn('secret-fixture', output.getvalue())
        self.assertIn('EMAILOPS_REVIEW_REASON=audit_unavailable', output.getvalue())


if __name__ == '__main__':
    unittest.main()
