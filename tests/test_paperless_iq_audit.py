import unittest
from governor.paperless_iq_audit import CHILD, sanitise
import json
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout
from pathlib import Path
import io


class IQAuditTests(unittest.TestCase):
    def test_safe_aggregate_packet(self):
        value = {'mutations': 'NONE', 'result': 'READ_ONLY_COMPLETE', 'pending_total': 10,
                 'db_auto_apply': False, 'source_main_sha256': 'a' * 64}
        self.assertEqual(sanitise(json.dumps(value)), value)

    def test_private_or_unbounded_output_is_rejected(self):
        base = {'mutations': 'NONE', 'result': 'READ_ONLY_COMPLETE'}
        for item in ({'document_text': 'private'}, {'db_auto_apply': 'secret'},
                     {'pending_total': True}, {'pending_total': -1},
                     {'source_main_sha256': 'private'}, {'result': 'private'},
                     {'mutations': 'WRITE'}):
            with self.subTest(keys=list(item)), self.assertRaises(ValueError):
                sanitise(json.dumps({**base, **item}))

    def test_child_compiles_and_does_not_start_application(self):
        compile(CHILD, 'fixed-iq-audit', 'exec')
        self.assertIn('?mode=ro', CHILD)
        self.assertIn('PRAGMA query_only=ON', CHILD)
        self.assertNotIn('import backend', CHILD)
        self.assertIn('signal.alarm(35)', CHILD)

    def test_missing_optional_sources_do_not_prevent_dependency_probes(self):
        config = {'auto_apply': False, 'automation_enabled': True,
                  'llm_provider': 'ollama', 'llm_model': 'gpt-oss:20b',
                  'ollama_url': 'http://ollama:11434'}
        connection = MagicMock()
        def execute(sql):
            cursor = MagicMock()
            cursor.fetchone.return_value = (json.dumps(config),) if 'SELECT config_json' in sql else (10,)
            return cursor
        connection.execute.side_effect = execute
        def response(request, timeout):
            data = {'status': 'ok', 'documents_total': 2772,
                    'models': [{'name': 'gpt-oss:20b'}]}
            obj = MagicMock()
            obj.status = 200
            obj.read.return_value = json.dumps(data).encode()
            obj.__enter__.return_value = obj
            return obj
        opener = MagicMock()
        opener.open.side_effect = response
        output = io.StringIO()
        with patch('sqlite3.connect', return_value=connection), patch('signal.alarm'), \
             patch('urllib.request.build_opener', return_value=opener), \
             patch('socket.getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 8080))]), \
             patch('importlib.metadata.version', return_value='1.2.0'), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'stat', side_effect=FileNotFoundError), \
             patch.dict('os.environ', {'PAPERLESS_URL': 'http://paperless:8000', 'PAPERLESS_TOKEN': 'fixture-only'}, clear=True), \
             redirect_stdout(output):
            exec(CHILD, {})
        data = sanitise(output.getvalue())
        self.assertEqual(data['feature_settings_cached'], 'UNKNOWN')
        self.assertEqual(data['feature_explicit_temperature'], 'UNKNOWN')
        self.assertEqual(data['paperless_http'], 200)
        self.assertEqual(data['ollama_http'], 200)
        self.assertTrue(data['iq_health_ok'])
        self.assertEqual(data['version'], '1.2.0')
        self.assertEqual(data['result'], 'PARTIAL_OR_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
