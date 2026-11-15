import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location('audit', pathlib.Path(__file__).parents[1] / 'governor/paperless_capability_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class CapabilityAuditTests(unittest.TestCase):
    def test_native_stdout_cannot_leak_values_or_inject_markers(self):
        import json
        self.assertEqual(audit.native_result('PRIVATE'), {'RESULT': 'OUTPUT_REJECTED'})
        data = {'DOCUMENTS': 942, 'VERSION': '3.1.2', 'RESULT': 'READ_ONLY_COMPLETE'}
        output = audit.native_result('private banner\nPAPERLESS_NATIVE_JSON=' + json.dumps(data))
        self.assertEqual(output['DOCUMENTS'], 942)
        self.assertNotIn('private', repr(output))
        data['secret'] = 'PRIVATE'
        self.assertEqual(audit.native_result('PAPERLESS_NATIVE_JSON=' + json.dumps(data)), {'RESULT': 'OUTPUT_REJECTED'})
        self.assertEqual(audit.native_result('x' * 32769), {'RESULT': 'OUTPUT_REJECTED'})

    def test_native_wrong_types_are_unknown(self):
        import json
        output = audit.native_result('PAPERLESS_NATIVE_JSON=' + json.dumps({'DOCUMENTS': True, 'VERSION': 'private\nX=PASS', 'RESULT': 'PRIVATE'}))
        self.assertEqual(output['DOCUMENTS'], 'UNKNOWN')
        self.assertEqual(output['VERSION'], 'UNKNOWN')
        self.assertEqual(output['RESULT'], 'OUTPUT_REJECTED')

    def test_only_selected_aggregates_leave_host(self):
        seen = []
        def get(path):
            seen.append(path)
            if path == 'statistics/':
                return {**dict.fromkeys(audit.STATS, 12), 'title': 'PRIVATE', 'inbox_tags': [99]}
            if path == 'ui_settings/':
                return {'user': {'username': 'PRIVATE'}, 'settings': {'version': '3.1.2', 'auditlog_enabled': True, 'ai_enabled': False, 'app_title': 'PRIVATE'}}
            return {'count': 3, 'results': [{'name': 'PRIVATE'}]}
        output = audit.collect(get)
        self.assertNotIn('PRIVATE', repr(output))
        self.assertEqual(output['DOCUMENTS_TOTAL'], 12)
        self.assertEqual(output['COMPLETENESS'], 'AVAILABLE')
        self.assertEqual(len(seen), 6)
        self.assertTrue(all(p.endswith('/?page_size=1') for p in seen[1:6]))

    def test_invalid_values_never_become_evidence(self):
        def get(path):
            return {'count': True, 'documents_total': -1, 'settings': {'version': 'PRIVATE\nX=PASS', 'auditlog_enabled': 'true'}}
        output = audit.collect(get)
        self.assertEqual(output['WORKFLOWS_COUNT'], 'UNKNOWN')
        self.assertEqual(output['DOCUMENTS_TOTAL'], 'UNKNOWN')
        self.assertNotIn('PRIVATE', repr(output))
        self.assertEqual(output['COMPLETENESS'], 'PARTIAL')

    def test_unavailable_is_not_zero_or_acceptance(self):
        output = audit.collect(lambda _: None)
        self.assertEqual(output['DOCUMENTS_TOTAL'], 'UNKNOWN')
        self.assertEqual(output['COMPLETENESS'], 'PARTIAL')
        self.assertNotIn('PASS', output.values())

    def test_redirect_refused(self):
        self.assertIsNone(audit.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))


if __name__ == '__main__':
    unittest.main()
