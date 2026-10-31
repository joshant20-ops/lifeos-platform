"""Isolated encrypted-backup transaction tests; no real Docker/restic/network."""
import contextlib
import importlib.util
import importlib.machinery
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

BASE = Path(__file__).resolve().parents[1]

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

BACKUP = module('audiobooks_backup_test', 'services/audiobookshelf/backup.py')
REAL_COMMAND = BACKUP.command
ACCESS = module('audiobooks_backup_access_test', 'services/audiobookshelf/configure_access.py')
IMAGE = 'ghcr.io/advplyr/audiobookshelf:2.37.2'
DIGEST = 'ghcr.io/advplyr/audiobookshelf@sha256:' + 'a' * 64
SNAPSHOT = 'b' * 64


class BackupTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        self.root = self.base / 'private-audiobooks'
        self.root.mkdir(mode=0o700)
        (self.root / 'config').mkdir(mode=0o700)
        self.helper = self.base / 'lifeos-restic-backup'
        self.password = self.base / 'restic-password'
        self.password.write_text('test-private-password')
        self.password.chmod(0o600)
        self.original = '#!/bin/sh\nrestic backup \\\n    /mnt/docker-data/automation/secrets\n'
        self.desired = '#!/bin/sh\nrestic backup \\\n    /mnt/docker-data/automation/secrets \\\n    /mnt/docker-data/audiobookshelf\n'
        source = self.repo / 'homelab/live/usr/local/sbin/lifeos-restic-backup'
        source.parent.mkdir(parents=True)
        source.write_text(self.desired)
        self.helper.write_text(self.original)
        self.helper.chmod(0o755)
        template = self.repo / 'services/audiobookshelf/compose.yaml'
        template.parent.mkdir(parents=True)
        template.write_text('services:\n  audiobookshelf:\n    image: ' + IMAGE + '\n')
        self.manifest = self.root / 'installation.json'
        self.manifest.write_text(json.dumps({'image': DIGEST}))
        self.manifest.chmod(0o600)
        self.compose = self.root / 'compose.yaml'
        self.compose.write_text(template.read_text().replace(IMAGE, DIGEST))
        self.compose.chmod(0o600)
        self.database = self.root / 'config/absdatabase.sqlite'
        self.database.write_bytes(b'test-only-sqlite-content')
        self.database.chmod(0o600)
        self.baseline = {'own': ('old-own-start', None), 'unrelated': ('old-start', 'healthy')}
        self.native = types.SimpleNamespace(IMAGE=IMAGE, snapshot=Mock(side_effect=[self.baseline, {'own': ('new-own-start', None), 'unrelated': ('old-start', 'healthy')}]), status=Mock(return_value={'isInit': True}))
        self.calls = []
        self.output = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.previous_umask = os.umask(0o022)
        self.addCleanup(os.umask, self.previous_umask)
        for name, value in [('REPO', self.repo), ('ROOT', self.root), ('HELPER', self.helper), ('PASSWORD', self.password)]:
            self.stack.enter_context(patch.object(BACKUP, name, value))
        self.stack.enter_context(patch.object(BACKUP.os, 'geteuid', return_value=0))
        real_stat = os.stat
        def root_owned(path, *args, **kwargs):
            value = real_stat(path, *args, **kwargs)
            fields = list(value)
            fields[4] = 0
            return os.stat_result(fields)
        self.stack.enter_context(patch.object(os, 'stat', side_effect=root_owned))
        self.stack.enter_context(patch.object(BACKUP.sys, 'argv', ['backup.py']))
        self.stack.enter_context(patch.object(BACKUP.time, 'sleep'))
        self.stack.enter_context(patch.object(BACKUP, 'load', side_effect=lambda name, path: self.native if name == 'install_helpers' else ACCESS))
        self.runner = self.stack.enter_context(patch.object(BACKUP, 'command', side_effect=self.command))
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.backup_error = None
        self.dump_mismatch = False
        self.start_error = False
        self.stop_error = False

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ('/usr/bin/restic', 'backup'):
            if self.backup_error:
                raise self.backup_error
            return (json.dumps({'message_type': 'verbose_status', 'item': 'PRIVATE_TITLE_SENTINEL'}) + '\n' + json.dumps({'message_type': 'summary', 'snapshot_id': SNAPSHOT}) + '\n').encode()
        if args[:2] == ('/usr/bin/restic', 'dump'):
            return b'wrong' if self.dump_mismatch else Path(args[-1]).read_bytes()
        if args[0] == '/usr/bin/docker':
            if args[-2:] == ('ps', '-q'):
                return b'own\n'
            if args[-1] == 'stop' and self.stop_error:
                raise subprocess.CalledProcessError(1, args)
            if args[-1] == 'start' and self.start_error:
                raise subprocess.CalledProcessError(1, args)
        return b''

    def test_success_stops_then_encrypts_and_decrypts_database_before_restart(self):
        BACKUP.main()
        stop = next(i for i, call in enumerate(self.calls) if call[-1] == 'stop')
        backup = next(i for i, call in enumerate(self.calls) if call[:2] == ('/usr/bin/restic', 'backup'))
        dumps = [i for i, call in enumerate(self.calls) if call[:2] == ('/usr/bin/restic', 'dump')]
        start = next(i for i, call in enumerate(self.calls) if call[-1] == 'start')
        self.assertLess(stop, backup)
        self.assertTrue(all(backup < i < start for i in dumps))
        self.assertEqual(len(dumps), 2)
        self.assertEqual(self.helper.read_text(), self.desired)
        self.assertEqual(self.helper.stat().st_mode & 0o777, 0o755)
        self.assertIn('AUDIOBOOKS_DATABASE_RESTORE=PASS', self.output.getvalue())
        self.assertNotIn('PRIVATE_TITLE_SENTINEL', self.output.getvalue())
        self.assertNotIn('test-private-password', self.output.getvalue())
        proof = json.loads((self.root / 'backup-proof.json').read_text())
        self.assertEqual(proof['snapshot'], SNAPSHOT)
        self.assertEqual((self.root / 'scheduled-backup-helper.before').stat().st_mode & 0o777, 0o600)

    def test_refuses_non_root_before_commands(self):
        with patch.object(BACKUP.os, 'geteuid', return_value=1000), self.assertRaises(ValueError):
            BACKUP.main()
        self.assertFalse(self.calls)

    def test_refuses_arguments_before_commands(self):
        with patch.object(BACKUP.sys, 'argv', ['backup.py', 'anything']), self.assertRaises(ValueError):
            BACKUP.main()
        self.assertFalse(self.calls)

    def test_refuses_password_symlink_without_reading_secret(self):
        self.password.unlink()
        self.password.symlink_to(self.database)
        with self.assertRaisesRegex(ValueError, 'backup password'):
            BACKUP.main()
        self.assertFalse(self.calls)

    def test_refuses_password_public_permissions(self):
        self.password.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'backup password'):
            BACKUP.main()
        self.assertFalse(self.calls)

    def test_refuses_helper_drift_before_stopping_service(self):
        self.helper.write_text('unrecognized helper')
        with self.assertRaisesRegex(ValueError, 'helper drift'):
            BACKUP.main()
        self.assertFalse(any(call[-1] == 'stop' for call in self.calls))

    def test_refuses_compose_drift_before_stopping_service(self):
        self.compose.write_text('arbitrary project')
        with self.assertRaisesRegex(ValueError, 'compose drift'):
            BACKUP.main()
        self.assertFalse(any(call[-1] == 'stop' for call in self.calls))

    def test_restic_failure_restarts_service_without_scheduling_unproven_backup(self):
        self.backup_error = subprocess.CalledProcessError(1, ['restic'])
        with self.assertRaises(subprocess.CalledProcessError):
            BACKUP.main()
        self.assertTrue(any(call[-1] == 'start' for call in self.calls))
        self.assertEqual(self.helper.read_text(), self.original)
        self.assertFalse((self.root / 'backup-proof.json').exists())
        self.assertNotIn('AUDIOBOOKS_ENCRYPTED_BACKUP=PASS', self.output.getvalue())

    def test_corrupt_dump_restarts_service_and_refuses_success(self):
        self.dump_mismatch = True
        with self.assertRaisesRegex(ValueError, 'restoration mismatch'):
            BACKUP.main()
        self.assertTrue(any(call[-1] == 'start' for call in self.calls))
        self.assertEqual(self.helper.read_text(), self.original)

    def test_unrelated_regression_refuses_schedule_change(self):
        self.native.snapshot.side_effect = [self.baseline, {'own': ('new-own-start', None), 'unrelated': ('different-start', 'healthy')}]
        with self.assertRaisesRegex(ValueError, 'unrelated container regression'):
            BACKUP.main()
        self.assertEqual(self.helper.read_text(), self.original)

    def test_already_included_helper_is_idempotent(self):
        self.helper.write_text(self.desired)
        BACKUP.main()
        self.assertEqual(self.helper.read_text(), self.desired)
        self.assertFalse((self.root / 'scheduled-backup-helper.before').exists())

    def test_failed_snapshot_still_verifies_restart_and_baseline(self):
        self.backup_error = subprocess.CalledProcessError(1, ['restic'])
        with self.assertRaises(subprocess.CalledProcessError):
            BACKUP.main()
        self.assertGreaterEqual(self.native.status.call_count, 1)
        self.assertEqual(self.native.snapshot.call_count, 2)

    def test_refuses_symlinked_database_directory_before_service_stop(self):
        outside = self.base / 'outside-config'
        (self.root / 'config').rename(outside)
        (self.root / 'config').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink|unsafe directory'):
            BACKUP.main()
        self.assertFalse(any(call[-1] == 'stop' for call in self.calls))

    def test_failed_start_emits_operator_required_without_backup_success(self):
        self.start_error = True
        with self.assertRaises(subprocess.CalledProcessError):
            BACKUP.main()
        self.assertIn('AUDIOBOOKS_RESTART=FAILED_OPERATOR_REQUIRED', self.output.getvalue())
        self.assertNotIn('AUDIOBOOKS_ENCRYPTED_BACKUP=PASS', self.output.getvalue())
        self.assertEqual(self.helper.read_text(), self.original)

    def test_stop_failure_still_starts_and_proves_health(self):
        self.stop_error = True
        with self.assertRaises(subprocess.CalledProcessError):
            BACKUP.main()
        self.assertTrue(any(call[-1] == 'start' for call in self.calls))
        self.assertGreaterEqual(self.native.status.call_count, 1)
        self.assertEqual(self.native.snapshot.call_count, 2)
        self.assertFalse(any(call[:2] == ('/usr/bin/restic', 'backup') for call in self.calls))

    def test_command_uses_fixed_repository_and_password_file_without_shell(self):
        with patch.object(BACKUP, 'command', REAL_COMMAND), patch.object(BACKUP.subprocess, 'run', return_value=types.SimpleNamespace(stdout=b'ok')) as runner:
            self.assertEqual(BACKUP.command('/usr/bin/restic', 'backup'), b'ok')
        args, options = runner.call_args
        self.assertEqual(args, (('/usr/bin/restic', 'backup'),))
        self.assertEqual(options['env']['RESTIC_REPOSITORY'], '/mnt/synology-backups/restic/lifeos-pi5')
        self.assertEqual(options['env']['RESTIC_PASSWORD_FILE'], '/etc/lifeos/restic-password')
        self.assertNotIn('shell', options)
        self.assertNotIn('test-private-password', str(runner.call_args))

    def test_fixed_gateway_accepts_only_named_backup_operation_without_arguments(self):
        path = BASE / 'homelab/live/usr/local/sbin/lifeos-deploy-gateway'
        loader = importlib.machinery.SourceFileLoader('audiobooks_backup_gateway_test', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        gateway = importlib.util.module_from_spec(spec)
        loader.exec_module(gateway)
        self.assertEqual(gateway.OPS['backup-audiobooks'], {'script': 'scripts/lifeos-backup-audiobooks.sh', 'privileged': True})
        self.assertEqual(gateway.parse_request(['backup-audiobooks']), ('backup-audiobooks', []))
        for args in [['backup-audiobooks', 'arbitrary'], ['backup-audiobooks', '/tmp/script.sh'], ['backup-audiobooks;id']]:
            with self.assertRaises(SystemExit):
                gateway.parse_request(args)

    def test_backup_issue_trigger_remains_inside_trusted_author_gate(self):
        workflow = (BASE / '.github/workflows/lifeos-pi-deploy.yml').read_text()
        start = workflow.index("((github.event.issue.title == 'LifeOS Deploy: install-audiobooks'")
        end = workflow.index("github.event.issue.title == 'LifeOS Deploy: discover-house-status'", start)
        guard = workflow[start:end]
        self.assertIn("github.event.issue.title == 'LifeOS Deploy: backup-audiobooks'", guard)
        self.assertIn('github.event.issue.author_association', guard)
        self.assertIn('["OWNER","MEMBER","COLLABORATOR"]', guard)
        self.assertIn('sudo -n bash /home/joshan/lifeos-platform/scripts/lifeos-install-github-runner-gateway.sh', workflow)
        self.assertIn('tests.test_audiobooks_backup', (BASE / '.github/workflows/lifeos-ci.yml').read_text())

    def test_wrapper_keeps_no_args_and_isolated_environment(self):
        wrapper = (BASE / 'scripts/lifeos-backup-audiobooks.sh').read_text()
        self.assertIn('$# -eq 0 && $EUID -eq 0', wrapper)
        self.assertIn('/usr/bin/env -i', wrapper)
        self.assertIn('/usr/bin/python3 -I', wrapper)


if __name__ == '__main__':
    unittest.main()
