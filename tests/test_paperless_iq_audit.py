import unittest
from governor.paperless_iq_audit import CHILD, sanitise, runtime_metadata, host_resources, docker_capacity_summary, build_cache_manifest
import json
import ast
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout
from pathlib import Path
import io


class IQAuditTests(unittest.TestCase):
    def test_runtime_metadata_uses_only_fixed_enums_and_worker_declarations(self):
        fixture = {'Config': {'Labels': {
            'com.docker.compose.project': 'paperless',
            'com.docker.compose.service': 'paperless-iq',
            'com.docker.compose.project.working_dir': '/home/joshan/paperless',
            'com.docker.compose.project.config_files': '/home/joshan/paperless/docker-compose.yml'},
            'Env': ['SECRET_KEY=private', 'WEB_CONCURRENCY=1'],
            'Entrypoint': [], 'Cmd': ['uvicorn', 'private.module:app', '--workers', '1']},
            'Mounts': [{'Destination': '/data', 'Source': '/private/data', 'Type': 'bind'}],
            'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}}}
        report = runtime_metadata(fixture)
        self.assertEqual(report['compose_layout'], 'HOME_PAPERLESS')
        self.assertTrue(report['single_worker_declared'])
        self.assertEqual(report['data_mount_type'], 'bind')
        self.assertNotIn('private', json.dumps(report))
        fixture['Config']['Env'].append('UVICORN_WORKERS=2')
        self.assertFalse(runtime_metadata(fixture)['single_worker_declared'])
        fixture['Config']['Cmd'] = ['sh', '-c', 'uvicorn private --workers 1']
        self.assertEqual(runtime_metadata(fixture)['single_worker_declared'], 'UNKNOWN')

    def test_all_six_preimages_and_resource_facts_are_sanitised(self):
        packet = {'mutations': 'NONE', 'result': 'READ_ONLY_COMPLETE',
                  'db_allocated_kib': 80000, 'inside_resource_budget_ok': False,
                  'source_models_sha256': 'a' * 64, 'source_queue_sha256': 'b' * 64}
        self.assertEqual(sanitise(json.dumps(packet)), packet)
        self.assertIn("len(sources) == 6", CHILD)
        self.assertIn("'backend/models.py'", CHILD)
        self.assertIn("'backend/approval_queue.py'", CHILD)

    def test_image_overlay_and_default_single_worker_are_distinguished(self):
        data = {'Config': {'Cmd': ['uvicorn', 'backend.main:app', '--host', '0.0.0.0',
            '--port', '8080', '--log-level', 'info']}, 'Mounts': []}
        self.assertTrue(runtime_metadata(data)['single_worker_default_command'])
        self.assertFalse(runtime_metadata(data)['application_mount_overlay'])
        for destination in ('/app/backend/main.py', '/app/src/backend'):
            data['Mounts'] = [{'Destination': destination}]
            self.assertTrue(runtime_metadata(data)['application_mount_overlay'])

    def test_allocated_database_over_ten_megabytes_is_reported_in_kib(self):
        tree = ast.parse(CHILD)
        block = next(node for node in tree.body if isinstance(node, ast.Try)
                     and 'db_allocated_kib' in ast.unparse(node))
        fake_path = MagicMock()
        fake_path.exists.return_value = True
        fake_path.stat.return_value = SimpleNamespace(st_blocks=20 * 1024 * 1024 // 512)
        scope = {'pathlib': SimpleNamespace(Path=MagicMock(return_value=fake_path)),
                 'out': {}, 'number': lambda n: n if n <= 10000000 else 'UNKNOWN'}
        exec(compile(ast.Module(body=[block], type_ignores=[]), 'allocated-db-probe', 'exec'), scope)
        self.assertEqual(scope['out']['db_allocated_kib'], 40 * 1024)

    def test_docker_capacity_does_not_scan_or_run_cleanup(self):
        with patch('subprocess.run', side_effect=[
                SimpleNamespace(stdout='/mnt/docker-data/docker'),
                SimpleNamespace(stdout='Driver: docker\nEndpoint: default'),
                SimpleNamespace(stdout='unix:///var/run/docker.sock'),
                SimpleNamespace(stdout='')]) as run, \
                patch.object(Path, 'is_mount', return_value=True), \
                patch.object(Path, 'stat', return_value=SimpleNamespace(st_dev=8)):
            result = docker_capacity_summary()
        self.assertTrue(result['docker_root_on_hdd'])
        self.assertTrue(result['default_builder_local_docker'])
        self.assertEqual(result['build_cache_manifest']['records'], [])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertNotIn('system', str(commands))
        self.assertNotIn('prune', str(commands))
        self.assertNotIn('--bootstrap', str(commands))

    def test_capacity_failure_reports_only_fixed_stage_and_reason(self):
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(
                1, ['docker'], stderr='unknown flag: --format private-content')):
            result = docker_capacity_summary()
        self.assertEqual(result, {'status': 'UNAVAILABLE', 'failed_stage': 'DOCKER_ROOT',
                                 'reason': 'CLI_UNSUPPORTED'})
        self.assertNotIn('private', json.dumps(result))

    def test_cache_manifest_uses_lifecycle_state_not_age_or_description(self):
        base = {'ID': 'a' * 25, 'Size': str(600 * 1024**2), 'Reclaimable': True,
                'Mutable': False, 'Shared': False, 'Type': 'regular',
                'Description': 'private source path', 'CreatedAt': 'unknown'}
        rows = [base]
        for index, change in enumerate(({'Reclaimable': False}, {'Mutable': True},
                {'Shared': True}, {'Type': 'source.local'}, {'Size': 'private'}), 1):
            rows.append({**base, 'ID': chr(97 + index) * 25, **change})
        report = build_cache_manifest('\n'.join(map(json.dumps, rows)))
        self.assertEqual(report['records'], [{'id': 'a' * 25, 'estimated_bytes': 600 * 1024**2}])
        self.assertFalse(report['deletion_authorised'])
        self.assertNotIn('private', json.dumps(report))
        with self.assertRaises(ValueError):
            build_cache_manifest('\n'.join(map(json.dumps, [base, base])))
        with self.assertRaises(ValueError):
            build_cache_manifest('[]')

    def test_unrecognised_compose_paths_and_labels_stay_unknown(self):
        report = runtime_metadata({'Config': {'Labels': {
            'com.docker.compose.project': 'private',
            'com.docker.compose.service': 'private',
            'com.docker.compose.project.working_dir': '/private',
            'com.docker.compose.project.config_files': '/private/compose.yml'}}})
        self.assertEqual(report['compose_layout'], 'UNKNOWN')
        self.assertNotIn('private', json.dumps(report))

    def test_unmounted_data_cannot_claim_a_reserve(self):
        with patch.object(Path, 'is_mount', return_value=False), \
             patch.object(Path, 'read_text', side_effect=OSError), \
             patch('os.getloadavg', return_value=(1.25, 1, 1)):
            report = host_resources()
        self.assertEqual(report['cpu_load_milli'], 1250)
        self.assertEqual(report['free_data_bytes'], 'UNKNOWN')
        self.assertEqual(report['data_reserve_met'], 'UNKNOWN')

    def test_actual_storage_reserve_checks_bytes_and_inodes(self):
        stats = MagicMock(f_bavail=20 * 1024**3, f_frsize=1,
                          f_blocks=100 * 1024**3, f_bfree=25 * 1024**3,
                          f_files=1000, f_favail=100)
        with patch.object(Path, 'is_mount', return_value=True), \
             patch.object(Path, 'read_text', side_effect=OSError), \
             patch('os.statvfs', return_value=stats):
            report = host_resources()
            self.assertTrue(report['data_reserve_met'])
            self.assertEqual(report['free_data_bytes'], 20 * 1024**3)
            stats.f_favail = 99
            self.assertFalse(host_resources()['data_reserve_met'])

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
