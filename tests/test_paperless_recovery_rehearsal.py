import hashlib
import os
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import sqlite3
import json
from unittest.mock import patch

from governor import paperless_recovery_rehearsal as rehearsal


def archive(name, kind=tarfile.REGTYPE, data=b"private fixture"):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as output:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.size = len(data) if kind == tarfile.REGTYPE else 0
        output.addfile(member, io.BytesIO(data) if member.size else None)
    buffer.seek(0)
    return buffer


class RecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        original_stat = Path.stat
        def stage_stat(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if '.paperless-restore-abcdefgh' in path.parts:
                from types import SimpleNamespace
                values = {field: getattr(result, field) for field in dir(result) if field.startswith('st_')}
                values['st_uid'] = 0  # Model the root-owned production staging boundary.
                return SimpleNamespace(**values)
            return result
        mocked = patch.object(Path, 'stat', stage_stat)
        mocked.start()
        self.addCleanup(mocked.stop)

    def cleanup_fixture(self, directory):
        root = Path(directory)
        reports = root / 'reports'
        reports.mkdir()
        stage = root / '.paperless-restore-abcdefgh'
        stage.mkdir(mode=0o700)
        (stage / 'db').mkdir()
        identifier = 'a' * 32
        record = {'archives_verified': 5, 'postgres_restore': 'PASS', 'originals_checked': 2772,
                  'originals_missing': 0, 'originals_checksum_mismatch': 0, 'temporary_stop': 'PASS', 'iq_temporary_cleanup': 'PASS'}
        (reports / (identifier + '.json')).write_text(json.dumps(record))
        info = {'Id': 'b' * 64, 'State': {'Status': 'exited', 'Running': False},
                'HostConfig': {'NetworkMode': 'none', 'PortBindings': {}},
                'Config': {'Labels': {'lifeos.paperless-rehearsal': 'true'}},
                'Mounts': [{'Type': 'bind', 'Destination': '/rehearsal', 'Source': str(stage / 'db')}]}
        return root, reports, stage, info

    def test_verified_cleanup_resumes_after_stage_deleted_and_container_remove_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root, reports, stage, info = self.cleanup_fixture(directory)
            def responses(remove):
                return ['b' * 12, json.dumps(info), 'b' * 12, info['Id'] + '|' + json.dumps(info['Mounts']), remove]
            with patch.object(rehearsal, 'HDD', root), patch.object(rehearsal, 'REPORT_DIR', reports):
                with patch.object(rehearsal, 'command', side_effect=responses(None)):
                    with self.assertRaises(rehearsal.RehearsalError):
                        rehearsal.cleanup_verified_staging(lambda: None, {})
                self.assertFalse(stage.exists())
                self.assertTrue(next(reports.glob('*.json')).exists())
                evidence = {}
                with patch.object(rehearsal, 'command', side_effect=responses('')) as run:
                    rehearsal.cleanup_verified_staging(lambda: None, evidence)
                self.assertEqual(run.call_args_list[-1].args[0], [rehearsal.DOCKER, 'rm', '-v', info['Id']])
                self.assertEqual(evidence['verified_test_stages_removed'], 0)

    def test_verified_cleanup_rejects_running_unlabelled_and_unexpected_mounts(self):
        for mutation in ('running', 'unlabelled', 'extra_bind', 'extra_volume'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root, reports, stage, info = self.cleanup_fixture(directory)
                if mutation == 'running':
                    info['State'] = {'Status': 'running', 'Running': True}
                elif mutation == 'unlabelled':
                    info['Config']['Labels'] = {}
                else:
                    info['Mounts'].append({'Type': 'bind' if mutation == 'extra_bind' else 'volume',
                                           'Destination': '/production', 'Source': '/private', 'Name': 'production'})
                with patch.object(rehearsal, 'HDD', root), patch.object(rehearsal, 'REPORT_DIR', reports), patch.object(rehearsal, 'command', side_effect=['b' * 12, json.dumps(info)]):
                    with self.assertRaises(rehearsal.RehearsalError):
                        rehearsal.cleanup_verified_staging(lambda: None, {})
                self.assertTrue(stage.exists())

    def test_verified_cleanup_rejects_parent_and_child_container_references(self):
        for reference in ('parent', 'child'):
            with tempfile.TemporaryDirectory() as directory:
                root, reports, stage, info = self.cleanup_fixture(directory)
                other = root if reference == 'parent' else stage / 'media'
                refs = info['Id'] + '|' + json.dumps(info['Mounts']) + '\n' + 'c' * 64 + '|' + json.dumps([{'Type': 'bind', 'RW': reference == 'parent', 'Source': str(other)}])
                with patch.object(rehearsal, 'HDD', root), patch.object(rehearsal, 'REPORT_DIR', reports), patch.object(rehearsal, 'command', side_effect=['b' * 12, json.dumps(info), 'b' * 12 + '\n' + 'c' * 12, refs]):
                    with self.assertRaises(rehearsal.RehearsalError):
                        rehearsal.cleanup_verified_staging(lambda: None, {})
                self.assertTrue(stage.exists())

    def test_streamed_readback_hash_limits_bytes_without_spooling_private_data(self):
        import subprocess, sys
        for size, success in ((32, True), (33, False)):
            result = subprocess.run([sys.executable, '-I', '-c', rehearsal.STREAM_HASH, '32'],
                                    input=b'x' * size, capture_output=True, timeout=5)
            self.assertEqual(result.returncode == 0, success)
            if success:
                self.assertEqual(json.loads(result.stdout), {'size': size, 'sha256': hashlib.sha256(b'x' * size).hexdigest()})
            else:
                self.assertEqual(result.stdout, b'')

    def test_native_scope_checks_limits_before_exec_and_cleans_up_on_abort(self):
        import sys
        scope = '/system.slice/lifeos-paperless-checkpoint-' + 'a' * 32 + '.scope'
        for quota in ('25000 100000', '50000 100000'):
            def read(path, *args, **kwargs):
                if str(path) == '/proc/self/cgroup':
                    return '0::' + scope
                return {'cpu.max': quota, 'memory.max': str(768 * 1024**2),
                        'memory.swap.max': '0', 'pids.max': '64'}[path.name]
            with patch.object(Path, 'read_text', read), patch.object(sys, 'argv', ['scope-check', '/usr/bin/env', 'GOMAXPROCS=1', '/usr/bin/restic']), patch.object(os, 'execv') as execute:
                if quota.startswith('25000'):
                    exec(rehearsal.SCOPE_CHECK_EXEC, {})
                    execute.assert_called_once()
                else:
                    with self.assertRaises(AssertionError):
                        exec(rehearsal.SCOPE_CHECK_EXEC, {})
                    execute.assert_not_called()
        def command(args, guard, **kwargs):
            if args[0] == '/usr/bin/systemd-run':
                guard()
            return ''
        def guard():
            raise rehearsal.RehearsalError('PI_RESOURCE_LIMIT')
        with patch.object(rehearsal, 'command', side_effect=command) as run:
            with self.assertRaisesRegex(rehearsal.RehearsalError, 'PI_RESOURCE_LIMIT'):
                rehearsal.checkpoint_restic_command(['/usr/bin/restic'], ['snapshots'], guard)
        launch = run.call_args_list[0].args[0]
        self.assertIn('--property=CPUQuota=25%', launch)
        self.assertIn('--property=MemoryMax=768M', launch)
        checker = launch.index('/usr/bin/python3')
        self.assertEqual(launch[checker+1:checker+4], ['-I', '-B', '-c'])
        unit = next(value.split('=', 1)[1] for value in launch if value.startswith('--unit='))
        self.assertEqual(run.call_args_list[-2].args[0], ['/usr/bin/systemctl', 'stop', unit])
        self.assertEqual(run.call_args_list[-1].args[0][-1], unit)

    def test_temporary_copy_inventory_is_readonly_and_preserves_changed_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / 'checkpoint'
            checkpoint.mkdir()
            disk = root / 'disk'
            disk.mkdir()
            stage = disk / '.paperless-restore-abcdefgh'
            stage.mkdir(mode=0o700)
            reports = root / 'reports'
            reports.mkdir()
            hashes = {}
            for name in rehearsal.ARCHIVES:
                data = b'private dump fixture' if name == 'paperless.dump' else archive('document.txt').getvalue()
                (checkpoint / name).write_bytes(data)
                hashes[name] = hashlib.sha256(data).hexdigest()
                if name == 'paperless.dump':
                    (stage / name).write_bytes(data)
                else:
                    target = stage / name.removesuffix('.tar')
                    target.mkdir(mode=0o700)
                    rehearsal.extract(io.BytesIO(data), target, lambda: None, rehearsal.LIMIT)
            (stage / 'db').mkdir()
            (stage / 'sockets').mkdir()
            with patch.object(rehearsal, 'HDD', disk), patch.object(rehearsal, 'CHECKPOINT', checkpoint), patch.object(rehearsal, 'REPORT_DIR', reports), patch.object(rehearsal, 'validate_stage_references'):
                evidence = {'checkpoint_encrypted_copy': 'PASS'}
                rehearsal.temporary_copy_inventory(hashes, lambda: None, evidence)
                self.assertEqual(evidence['temporary_duplicate_exact_stages'], 1)
                self.assertTrue(stage.exists())
                manifest = json.loads(next(reports.glob('temporary-copy-dry-run-*.json')).read_text())
                self.assertEqual(manifest['mode'], 'DRY_RUN')
                self.assertEqual(manifest['exact_copies'][0]['stage'], str(stage))
                (stage / 'media' / 'document.txt').write_bytes(b'changed')
                evidence = {'checkpoint_encrypted_copy': 'PASS'}
                rehearsal.temporary_copy_inventory(hashes, lambda: None, evidence)
                self.assertEqual(evidence['temporary_duplicate_exact_stages'], 0)
                self.assertEqual(evidence['temporary_duplicate_protected_stages'], 1)
                self.assertEqual((stage / 'media' / 'document.txt').read_bytes(), b'changed')
                def guard():
                    raise rehearsal.RehearsalError('PI_RESOURCE_LIMIT')
                with self.assertRaisesRegex(rehearsal.RehearsalError, 'PI_RESOURCE_LIMIT'):
                    rehearsal.temporary_copy_inventory(hashes, guard, {'checkpoint_encrypted_copy': 'PASS'})

    def test_checkpoint_protection_uses_native_encryption_and_verifies_every_byte(self):
        import types, sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / 'checkpoint'
            checkpoint.mkdir()
            reports = root / 'reports'
            reports.mkdir()
            record = {'archives_verified': 5, 'postgres_restore': 'PASS', 'originals_checked': 1,
                      'originals_missing': 0, 'originals_checksum_mismatch': 0, 'temporary_stop': 'PASS'}
            (reports / ('a' * 32 + '.json')).write_text(json.dumps(record))
            files = {name: ('fixture-' + name).encode() for name in (*rehearsal.ARCHIVES, 'SHA256SUMS')}
            for name, data in files.items():
                (checkpoint / name).write_bytes(data)
            (checkpoint / 'additional-owner-evidence').write_bytes(b'preserve without reading or copying')
            hashes = {name: hashlib.sha256(files[name]).hexdigest() for name in rehearsal.ARCHIVES}
            module = types.ModuleType('governor.adguard_archive_restic_proof')
            module.SHARE = root / 'share'
            module.REPOSITORY = module.SHARE / 'restic/repo'
            module.REPOSITORY.mkdir(parents=True)
            module.PASSWORD_FILE = root / 'password'
            module.PASSWORD_FILE.write_bytes(b'fixture-only')
            module.PASSWORD_FILE.chmod(0o600)
            module.verify_nfs_mount = lambda fd: True
            original_fstat = os.fstat
            def owned_password(fd):
                value = original_fstat(fd)
                if Path('/proc/self/fd/' + str(fd)).resolve() == module.PASSWORD_FILE:
                    values = list(value)
                    values[4] = 0  # Model the required root-owned credential file.
                    return os.stat_result(values)
                return value
            state = {'exists': False, 'corrupt': False}
            def native(args, guard, **kwargs):
                guard()
                if 'snapshots' in args:
                    return json.dumps([{'id': 'b' * 64, 'time': '2026-11-18T00:00:00Z', 'paths': [str(checkpoint / name) for name in files]}] if state['exists'] else [])
                if 'backup' in args:
                    state['exists'] = True
                    return ''
                if 'findmnt' in args[0]:
                    return 'tmpfs'
                if args[0] == '/usr/bin/systemctl':
                    return ''
                if 'dump' in args:
                    data = files[Path(args[-1]).name]
                    data = b'X' * len(data) if state['corrupt'] else data
                    return json.dumps({'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                self.fail('Unexpected native command')
            with patch.object(rehearsal, 'resource_ready', return_value=True), patch.dict(sys.modules, {'governor.adguard_archive_restic_proof': module}), patch.object(rehearsal, 'CHECKPOINT', checkpoint), patch.object(rehearsal, 'REPORT_DIR', reports), patch.object(rehearsal.os, 'fstat', side_effect=owned_password), patch.object(rehearsal, 'command', side_effect=native) as run:
                evidence = {}
                rehearsal.protect_verified_checkpoint(hashes, lambda: None, evidence)
                self.assertEqual(evidence['checkpoint_encrypted_copy'], 'PASS')
                self.assertEqual(evidence['checkpoint_encrypted_files'], 6)
                self.assertEqual(evidence['checkpoint_additional_entries_preserved'], 1)
                self.assertTrue((checkpoint / 'additional-owner-evidence').exists())
                calls = [call.args[0] for call in run.call_args_list]
                self.assertEqual(sum('dump' in args for args in calls), 6)
                self.assertEqual(sum('backup' in args for args in calls), 1)
                backup_args = next(args for args in calls if 'backup' in args)
                self.assertEqual(set(backup_args[-6:]), {str(checkpoint / name) for name in files})
                self.assertNotIn(str(checkpoint), backup_args)
                self.assertFalse(any(token in args for args in calls for token in ('forget', 'prune', 'init', 'unlock')))
                self.assertTrue(all((checkpoint / name).read_bytes() == data for name, data in files.items()))
                run.reset_mock()
                cached = {}
                rehearsal.protect_verified_checkpoint(hashes, lambda: None, cached)
                self.assertEqual(cached['checkpoint_encrypted_copy'], 'CACHED_VERIFIED_COPY')
                self.assertFalse(any('dump' in call.args[0] or 'backup' in call.args[0] for call in run.call_args_list))
                (reports / 'encrypted-checkpoint-receipt.json').unlink()
                state['corrupt'] = True
                with self.assertRaisesRegex(rehearsal.RehearsalError, 'CHECKPOINT_READBACK_CHECKSUM'):
                    rehearsal.protect_verified_checkpoint(hashes, lambda: None, {})
                self.assertFalse((reports / 'encrypted-checkpoint-receipt.json').exists())

    def test_application_failure_evidence_rejects_private_or_unbounded_fields(self):
        for extra in ({}, {'private_contents': 'must never escape'}, {'application_listing_count': 'private value'}):
            with self.subTest(extra=list(extra)), tempfile.TemporaryDirectory() as directory:
                stage = Path(directory)
                (stage / 'media' / 'originals').mkdir(parents=True)
                diagnostic = {'application_failure_phase': 'DOCUMENT_LIST', 'application_failure_type': 'ConnectionError', **extra}
                evidence = {'root_documents': 2772}
                with patch.object(rehearsal, 'command', side_effect=['a' * 12, 'sha256:' + 'b' * 64, json.dumps(diagnostic), '']):
                    with self.assertRaises(rehearsal.RehearsalError):
                        rehearsal.application_proof(stage, 'isolated-test', lambda: None, evidence)
                self.assertNotIn('private_contents', evidence)
                if extra:
                    self.assertNotIn('application_failure_phase', evidence)
                else:
                    self.assertEqual(evidence['application_failure_type'], 'ConnectionError')

    def test_backup_inventory_never_swallows_guard_abort(self):
        import types, sys
        module = types.ModuleType('governor.adguard_archive_restic_proof')
        module.verify_nfs_mount = lambda fd: True
        module.SHARE = Path('/unavailable-test-share')
        module.REPOSITORY = module.SHARE / 'repo'
        module.PASSWORD_FILE = Path('/unavailable-test-password')
        for error in (rehearsal.RehearsalError('INTERRUPTED'), rehearsal.RehearsalError('PI_RESOURCE_LIMIT'), OSError('guard failed')):
            with patch.dict(sys.modules, {'governor.adguard_archive_restic_proof': module}):
                def guard():
                    raise error
                with self.assertRaises(type(error)):
                    rehearsal.backup_coverage_inventory(guard, {})
        with patch.dict(sys.modules, {'governor.adguard_archive_restic_proof': module}):
            evidence = {}
            rehearsal.backup_coverage_inventory(lambda: None, evidence)
            self.assertEqual(evidence['backup_inventory'], 'LOCAL_OS_ERROR')

    def test_backup_paths_are_metadata_scope_not_payload_recovery_proof(self):
        self.assertEqual(rehearsal.checkpoint_snapshot_path_count([{'paths': ['/opt/stacks']}]), 0)
        selected = [str(rehearsal.CHECKPOINT / name) for name in (*rehearsal.ARCHIVES, 'SHA256SUMS')]
        self.assertEqual(rehearsal.checkpoint_snapshot_path_count([{'paths': selected}]), 1)
        self.assertEqual(rehearsal.checkpoint_snapshot_path_count([{'paths': selected[:-1]}]), 0)
        self.assertEqual(rehearsal.checkpoint_snapshot_path_count([{'paths': [str(rehearsal.CHECKPOINT)]}, {'paths': ['/mnt/docker-data']}]), 2)
        self.assertEqual(rehearsal.checkpoint_snapshot_path_count([{'paths': [str(rehearsal.CHECKPOINT) + '-other']}]), 0)
        for malformed in (None, [{}], [{'paths': None}], [{'paths': ['/mnt/docker-data/../private']}], [{'paths': [1]}]):
            with self.assertRaises(rehearsal.RehearsalError):
                rehearsal.checkpoint_snapshot_path_count(malformed)

    def test_historical_format_inventory_exposes_only_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'private-json').write_bytes(b'{"private": "fixture"}')
            (root / 'private-binary').write_bytes(b'\xff\x00')
            (root / 'private-pdf').write_bytes(b'%PDF-fixture')
            result = rehearsal.historical_email_inventory(root, lambda: None)
            self.assertEqual(result['historical_signature_json'], 1)
            self.assertEqual(result['historical_signature_binary'], 1)
            self.assertEqual(result['historical_signature_pdf'], 1)
            self.assertTrue(all(type(value) is int for value in result.values()))

    def test_socket_directory_allows_distinct_uid_without_exposing_private_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            stage.chmod(0o700)
            with patch.object(rehearsal, 'postgres_image', return_value='sha256:' + 'a' * 64), patch.object(rehearsal, 'command', return_value=None) as run:
                with self.assertRaises(rehearsal.RehearsalError):
                    rehearsal.database_proof(stage, 'isolated-test', lambda: None, {})
            self.assertEqual((stage / 'sockets').stat().st_mode & 0o7777, 0o1777)
            self.assertEqual(stage.stat().st_mode & 0o777, 0o700)
            args = run.call_args.args[0]
            self.assertIn('unix_socket_directories=/var/run/postgresql,/rehearsal-sockets', args)
            self.assertIn('type=bind,src=' + str(stage / 'sockets') + ',dst=/rehearsal-sockets', args)
            # Others have write/search permission on sockets even when PG owns them;
            # the outer0700 directory and fixed Docker binds remain the authority.
            self.assertEqual((stage / 'sockets').stat().st_mode & 0o003, 0o003)

    def test_application_probe_has_no_network_production_mount_or_ingestion_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'media' / 'originals').mkdir(parents=True)
            proof = {key: 'PASS' for key in ('application_list', 'application_access_control',
                     'application_original_retrieval', 'application_index_rebuild', 'application_search_endpoint')}
            proof.update(application_documents=2772, application_retrieved_files=1)
            evidence = {'root_documents': 2772}
            with patch.object(rehearsal, 'command', side_effect=['a' * 12, 'sha256:' + 'b' * 64, json.dumps(proof), '']) as run:
                rehearsal.application_proof(stage, 'lifeos-paperless-rehearsal-' + 'c' * 32, lambda: None, evidence)
            args = run.call_args_list[2].args[0]
            self.assertIn('--network=none', args)
            self.assertIn('--read-only', args)
            self.assertIn('--cap-drop=ALL', args)
            self.assertIn('--entrypoint=python3', args)
            self.assertNotIn('-p', args)
            mounts = [args[i+1] for i, value in enumerate(args) if value == '--mount']
            self.assertEqual(len(mounts), 2)
            self.assertTrue(all(value.startswith('type=bind,src=' + str(stage) + '/') and value.endswith(',readonly') for value in mounts))
            self.assertEqual(evidence['application_restore'], 'DJANGO_API_PASS')
            self.assertEqual(evidence['application_temporary_cleanup'], 'PASS')

    def test_application_probe_failure_stops_and_removes_only_its_random_container(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'media' / 'originals').mkdir(parents=True)
            name = 'lifeos-paperless-rehearsal-' + 'c' * 32
            with patch.object(rehearsal, 'command', side_effect=['a' * 12, 'sha256:' + 'b' * 64, None, '', '']) as run:
                with self.assertRaises(rehearsal.RehearsalError):
                    rehearsal.application_proof(stage, name, lambda: None, {'root_documents': 2772})
            self.assertEqual(run.call_args_list[-2].args[0], [rehearsal.DOCKER, 'stop', '--time=3', name + '-app'])
            self.assertEqual(run.call_args_list[-1].args[0], [rehearsal.DOCKER, 'rm', '-v', name + '-app'])

    def test_readonly_strict_ancestor_observer_allows_verified_private_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root, reports, stage, info = self.cleanup_fixture(directory)
            refs = info['Id'] + '|' + json.dumps(info['Mounts']) + '\n' + 'c' * 64 + '|' + json.dumps([{'Type': 'bind', 'RW': False, 'Source': str(root)}])
            evidence = {}
            with patch.object(rehearsal, 'HDD', root), patch.object(rehearsal, 'REPORT_DIR', reports), patch.object(rehearsal, 'command', side_effect=['b' * 12, json.dumps(info), 'b' * 12 + '\n' + 'c' * 12, refs, '']):
                rehearsal.cleanup_verified_staging(lambda: None, evidence)
            self.assertFalse(stage.exists())
            self.assertEqual(evidence['verified_test_stages_removed'], 1)
            self.assertEqual(evidence['cleanup_readonly_ancestor_references'], 1)

    def test_stage_validation_rejects_unknown_children_and_nested_mounts(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _, stage, _ = self.cleanup_fixture(directory)
            (stage / 'unknown').touch()
            with patch.object(rehearsal, 'HDD', root), self.assertRaises(rehearsal.RehearsalError):
                rehearsal.validated_test_stage(str(stage / 'db'))
            (stage / 'unknown').unlink()
            with patch.object(rehearsal, 'HDD', root), patch.object(Path, 'open', return_value=io.StringIO(f'1 2 0:1 / {stage}/media rw - ext4 disk rw\n')), self.assertRaises(rehearsal.RehearsalError):
                rehearsal.validated_test_stage(str(stage / 'db'))

    def test_verified_stage_cleanup_requires_successful_original_recovery(self):
        record = {'archives_verified': 5, 'postgres_restore': 'PASS', 'originals_checked': 2772,
                  'originals_missing': 0, 'originals_checksum_mismatch': 0, 'temporary_stop': 'PASS'}
        self.assertTrue(rehearsal.verified_recovery_record(record))
        for field, value in (('archives_verified', 4), ('postgres_restore', 'FAILED'),
                             ('originals_checked', 0), ('originals_missing', 1),
                             ('originals_checksum_mismatch', 1), ('temporary_stop', 'UNVERIFIED')):
            self.assertFalse(rehearsal.verified_recovery_record({**record, field: value}))

    def test_cleanup_stage_rejects_production_paths(self):
        for path in ('/mnt/docker-data/paperless-recovery/checkpoint/db', '/home/joshan/paperless/data/db', '/mnt/docker-data/automation/db'):
            with self.assertRaises(rehearsal.RehearsalError):
                rehearsal.validated_test_stage(path)

    def test_cleanup_uses_only_recorded_exited_isolated_iq_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identifier = 'a' * 32
            (root / (identifier + '.json')).write_text(json.dumps({'chroma_native_restore': 'PASS'}))
            with patch.object(rehearsal, 'REPORT_DIR', root), patch.object(rehearsal, 'command', side_effect=['b' * 12, 'running|none|0|["python3"]']) as run:
                with self.assertRaises(rehearsal.RehearsalError):
                    rehearsal.recover_completed_iq_cleanup(lambda: None)
            self.assertEqual(run.call_count, 2)
            with patch.object(rehearsal, 'REPORT_DIR', root), patch.object(rehearsal, 'command', side_effect=['b' * 12, 'exited|none|0|["python3"]', '']) as run:
                rehearsal.recover_completed_iq_cleanup(lambda: None)
            args = run.call_args_list[-1].args[0]
            self.assertEqual(args, [rehearsal.DOCKER, 'rm', '-v', 'lifeos-paperless-rehearsal-' + identifier + '-iq'])

    def test_chroma_preserves_extra_disk_segment_and_requires_all_metadata_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with sqlite3.connect(root / 'paperless_iq.db') as db:
                db.execute('CREATE TABLE fixture (id INTEGER)')
            chroma = root / 'chroma'
            chroma.mkdir()
            with sqlite3.connect(chroma / 'chroma.sqlite3') as db:
                db.execute('CREATE TABLE segments (id TEXT, scope TEXT)')
                db.execute("INSERT INTO segments VALUES ('required', 'VECTOR')")
            for segment in ('required', 'extra'):
                path = chroma / segment
                path.mkdir()
                for name in ('header.bin', 'data_level0.bin', 'length.bin', 'link_lists.bin'):
                    (path / name).write_bytes(b'x')
            evidence = {}
            rehearsal.iq_verify(root, lambda: None, evidence)
            self.assertEqual(evidence['chroma_disk_segments_unmapped'], 1)
            self.assertEqual(evidence['chroma_vector_rows_without_disk'], 0)
            self.assertTrue((chroma / 'extra/header.bin').exists())
            (chroma / 'required/header.bin').unlink()
            with self.assertRaises(rehearsal.RehearsalError):
                rehearsal.iq_verify(root, lambda: None)

    def test_native_chroma_uses_isolated_image_and_staged_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'chroma.sqlite3').touch()
            image = 'sha256:' + 'a' * 64
            evidence = {}
            with patch.object(rehearsal, 'command', side_effect=[image, 'CHROMA_NATIVE_RESULT=[2,200,2]', '', '']) as run:
                rehearsal.chroma_native_proof(root, 'random-test', lambda: None, evidence)
            args = run.call_args_list[1].args[0]
            self.assertIn('--network=none', args)
            self.assertIn('--read-only', args)
            self.assertIn(f'type=bind,src={root},dst=/recovery', args)
            self.assertNotIn('-p', args)
            self.assertEqual(evidence['chroma_native_restore'], 'PASS')
            self.assertEqual(evidence['iq_temporary_cleanup'], 'PASS')
            self.assertFalse(any(call.args[0][1] == 'stop' for call in run.call_args_list))

    def test_failure_categories_suppress_private_exception_text(self):
        self.assertEqual(rehearsal.failure_code(OSError('private path')), 'LOCAL_OS_ERROR')
        self.assertEqual(rehearsal.failure_code(ValueError('PRIVATE_RECORD')), 'LOCAL_OPERATION_FAILED')
        self.assertEqual(rehearsal.failure_code(rehearsal.RehearsalError('POSTGRES_START')), 'POSTGRES_START')

    def test_historical_format_inventory_does_not_require_eml_or_emit_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('private.EML', 'private.tar', 'private.gz', 'private.bin'):
                (root / name).write_bytes(b'private')
            result = rehearsal.historical_email_inventory(root, lambda: None)
            self.assertEqual(result['historical_eml_files'], 1)
            self.assertEqual(result['historical_tar_files'], 1)
            self.assertEqual(result['historical_gzip_files'], 1)
            self.assertEqual(result['historical_other_files'], 1)
            self.assertNotIn('private', repr(result))
            (root / 'private.EML').unlink()
            self.assertEqual(rehearsal.historical_email_inventory(root, lambda: None)['historical_eml_files'], 0)

    def test_extract_preserves_bytes_under_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            source = archive("./originals/test.pdf")
            count, size = rehearsal.extract(source, target, lambda: None, 100)
            self.assertEqual((count, size), (1, 15))
            self.assertEqual((target / "originals/test.pdf").read_bytes(), b"private fixture")

    def test_extract_rejects_escape_links_and_over_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for source in (archive("../outside"), archive("/outside"), archive("link", tarfile.SYMTYPE), archive("large")):
                with self.assertRaises(ValueError):
                    rehearsal.extract(source, target, lambda: None, 5)
            self.assertEqual(list(target.iterdir()), [])

    def test_manifest_is_a_closed_set_of_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = hashlib.sha256(b"x").hexdigest()
            manifest = root / "SHA256SUMS"
            lines = [f"{digest}  ./{name}" for name in rehearsal.ARCHIVES]
            manifest.write_text("\n".join(lines))
            self.assertEqual(set(rehearsal.read_manifest(root)), set(rehearsal.ARCHIVES))
            manifest.write_text("\n".join([*lines[:-1], lines[0]]))
            with self.assertRaises(ValueError):
                rehearsal.read_manifest(root)
            (root / "link").symlink_to(manifest)
            with self.assertRaises(OSError), rehearsal.regular_source(root, "link"):
                pass


if __name__ == "__main__":
    unittest.main()

