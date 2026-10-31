"""Isolated transaction tests: no Docker, host storage, or network access."""
import contextlib
import importlib.util
import importlib.machinery
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'audiobooks_install_under_test', REPOSITORY / 'services/audiobookshelf/install.py')
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)
REAL_SNAPSHOT = INSTALL.snapshot
DIGEST = 'ghcr.io/advplyr/audiobookshelf@sha256:' + 'a' * 64
BASELINE = {'existing-container': ('original-start-time', 'healthy')}


class InstallationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'audiobookshelf'
        self.calls = []
        self.up_definitions = []
        self.output = io.StringIO()
        self.previous_umask = os.umask(0o022)
        self.addCleanup(os.umask, self.previous_umask)
        real_stat = os.stat

        def stat(path, *args, **kwargs):
            if str(path) in ('/opt/stacks', '/mnt/docker-data'):
                return types.SimpleNamespace(st_dev=123)
            result = real_stat(path, *args, **kwargs)
            if str(path).startswith(self.temp.name + '/'):
                # Model root-owned Pi files even when CI runs unprivileged.
                fields = list(result)
                fields[4] = 0
                return os.stat_result(fields)
            return result

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(INSTALL, 'ROOT', self.root))
        self.stack.enter_context(patch.object(INSTALL, 'REPO', REPOSITORY))
        self.stack.enter_context(patch.object(INSTALL.os, 'geteuid', return_value=0))
        self.stack.enter_context(patch.object(INSTALL.os, 'stat', side_effect=stat))
        self.stack.enter_context(patch.object(INSTALL.os, 'statvfs', return_value=types.SimpleNamespace(
            f_bavail=6 * 1024**3, f_frsize=1)))
        self.stack.enter_context(patch.object(INSTALL.sys, 'argv', ['install.py']))
        self.socket = self.stack.enter_context(patch('socket.socket'))
        self.stack.enter_context(patch.object(INSTALL.time, 'sleep'))
        self.run = self.stack.enter_context(patch.object(INSTALL, 'run', side_effect=self.command))
        self.snapshots = self.stack.enter_context(patch.object(
            INSTALL, 'snapshot', side_effect=[dict(BASELINE), dict(BASELINE)]))
        self.status = self.stack.enter_context(patch.object(INSTALL, 'status', side_effect=[
            {'isInit': False}, {'isInit': True}, {'isInit': True}]))
        self.request = self.stack.enter_context(patch.object(INSTALL, 'request', return_value=b'OK'))
        self.stack.enter_context(patch.object(INSTALL.secrets, 'token_urlsafe', return_value='test-only-secret'))
        self.stack.enter_context(contextlib.redirect_stdout(self.output))

    def command(self, *args):
        self.calls.append(args)
        if args[0] == '/usr/bin/findmnt':
            return 'system-uuid' if args[-1] == '/' else 'ssd-uuid'
        if args[1:3] == ('ps', '-aq'):
            return ''
        if args[1:3] == ('image', 'inspect'):
            return json.dumps([{'Architecture': 'arm64', 'Os': 'linux', 'RepoDigests': [DIGEST]}])
        if 'compose' in args and 'up' in args:
            self.up_definitions.append((self.root / 'compose.yaml').read_text())
        return ''

    def test_first_install_initializes_isolated_then_exposes_initialized_service(self):
        INSTALL.main()
        self.assertEqual(len(self.up_definitions), 2)
        bootstrap, final = self.up_definitions
        self.assertIn('audiobooks_bootstrap:', bootstrap)
        self.assertIn('internal: false', bootstrap)
        self.assertNotIn('reverse_proxy', bootstrap)
        self.assertNotIn('external: true', bootstrap)
        self.assertIn('reverse_proxy:', final)
        self.assertIn('external: true', final)
        self.assertIn(DIGEST, bootstrap)
        self.assertIn(DIGEST, final)
        self.assertNotIn(INSTALL.IMAGE, final)
        self.request.assert_called_once_with('/init', {'newRoot': {
            'username': 'lifeos-admin', 'password': 'test-only-secret'}})
        self.assertIn('AUDIOBOOKS_INSTALL=PASS', self.output.getvalue())
        self.assertNotIn('test-only-secret', self.output.getvalue())
        self.assertEqual(json.loads((self.root / 'installation.json').read_text())['image'], DIGEST)

    def test_credentials_and_data_are_private_and_written_before_init(self):
        def init(path, payload):
            secret_file = self.root / 'initial-admin.json'
            self.assertTrue(secret_file.exists())
            self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(secret_file.read_text()), payload['newRoot'])
            self.assertEqual(len(self.up_definitions), 1)
        self.request.side_effect = init
        INSTALL.main()
        for name in ('config', 'metadata', 'audiobooks'):
            self.assertEqual((self.root / name).stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_credentials_file_and_parent_are_synced_before_init(self):
        real_fsync = os.fsync
        synced = []
        def fsync(descriptor):
            real_fsync(descriptor)
            synced.append(descriptor)
        def init(path, payload):
            self.assertEqual(len(synced), 2)
            self.assertEqual(path, '/init')
        self.request.side_effect = init
        with patch.object(INSTALL.os, 'fsync', side_effect=fsync):
            INSTALL.main()

    def test_failed_credential_sync_never_initializes_server(self):
        with patch.object(INSTALL.os, 'fsync', side_effect=OSError('sync failed')):
            with self.assertRaises(OSError):
                INSTALL.main()
        self.request.assert_not_called()
        self.assertTrue(any('down' in call for call in self.calls))
        self.assertTrue((self.root / 'initial-admin.json').exists())

    def test_snapshot_rejects_unhealthy_or_nonrunning_container(self):
        for state in (
            {'Status': 'running', 'StartedAt': 't', 'Health': {'Status': 'unhealthy'}},
            {'Status': 'running', 'StartedAt': 't', 'Health': {'Status': 'starting'}},
            {'Status': 'restarting', 'StartedAt': 't'},
        ):
            with self.subTest(state=state):
                self.run.side_effect = ['container', json.dumps([{'Id': 'container', 'State': state}])]
                with self.assertRaisesRegex(ValueError, 'baseline container not healthy'):
                    REAL_SNAPSHOT()

    def test_snapshot_requires_at_least_one_baseline_container(self):
        self.run.side_effect = ['']
        with self.assertRaisesRegex(ValueError, 'no baseline containers'):
            REAL_SNAPSHOT()

    def test_snapshot_accepts_running_container_without_healthcheck(self):
        self.run.side_effect = ['container', json.dumps([{
            'Id': 'container', 'State': {'Status': 'running', 'StartedAt': 't'}}])]
        self.assertEqual(REAL_SNAPSHOT(), {'container': ('t', None)})

    def test_refuses_non_root_before_mutation(self):
        with patch.object(INSTALL.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(ValueError, 'root and no arguments'):
                INSTALL.main()
        self.run.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_refuses_arguments_before_mutation(self):
        with patch.object(INSTALL.sys, 'argv', ['install.py', '/arbitrary/path']):
            with self.assertRaisesRegex(ValueError, 'root and no arguments'):
                INSTALL.main()
        self.run.assert_not_called()

    def test_refuses_unproven_ssd(self):
        def command(*args):
            return 'same-as-system' if args[0] == '/usr/bin/findmnt' else self.command(*args)
        self.run.side_effect = command
        with self.assertRaisesRegex(ValueError, 'SSD stack mount not proven'):
            INSTALL.main()
        self.assertFalse(self.root.exists())
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_refuses_partial_migration(self):
        original_exists = Path.exists
        def exists(path):
            return True if str(path) == '/mnt/docker-data/.lifeos-opt-stacks-stage.partial' else original_exists(path)
        with patch.object(Path, 'exists', exists):
            with self.assertRaisesRegex(ValueError, 'incomplete storage migration'):
                INSTALL.main()
        self.assertFalse(self.root.exists())

    def test_refuses_low_capacity_without_creating_state(self):
        with patch.object(INSTALL.os, 'statvfs', return_value=types.SimpleNamespace(f_bavail=1, f_frsize=1)):
            with self.assertRaisesRegex(ValueError, 'less than 5 GiB'):
                INSTALL.main()
        self.assertFalse(self.root.exists())

    def test_existing_state_is_preserved_without_docker_mutation(self):
        self.root.mkdir()
        marker = self.root / 'existing-data'
        marker.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'not uninitialized bootstrap'):
            INSTALL.main()
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_dangling_symlink_is_refused(self):
        self.root.symlink_to(Path(self.temp.name) / 'missing-target')
        with self.assertRaisesRegex(ValueError, 'existing audiobook state preserved'):
            INSTALL.main()
        self.assertTrue(self.root.is_symlink())

    def prepare_bootstrap(self, internal=True):
        self.root.mkdir(mode=0o700)
        for name in ('config', 'metadata', 'audiobooks'):
            (self.root / name).mkdir(mode=0o700)
        source = (REPOSITORY / 'services/audiobookshelf/compose.yaml').read_text()
        definition = source.replace(INSTALL.IMAGE, DIGEST).replace('reverse_proxy', 'audiobooks_bootstrap')
        definition = definition.replace('external: true', 'internal: ' + str(internal).lower())
        path = self.root / 'compose.yaml'
        path.write_text(definition)
        path.chmod(0o600)
        marker = self.root / 'config' / 'preserved-app-state'
        marker.write_text('preserve-me')
        return definition

    def test_resume_legacy_bootstrap_keeps_digest_and_existing_data(self):
        self.prepare_bootstrap(internal=True)
        INSTALL.main()
        self.assertIn((INSTALL.DOCKER, 'pull', '--platform', 'linux/arm64', DIGEST), self.calls)
        self.assertNotIn((INSTALL.DOCKER, 'pull', '--platform', 'linux/arm64', INSTALL.IMAGE), self.calls)
        self.assertIn('internal: false', self.up_definitions[0])
        self.assertNotIn('reverse_proxy', self.up_definitions[0])
        self.assertEqual((self.root / 'config' / 'preserved-app-state').read_text(), 'preserve-me')
        self.assertIn('AUDIOBOOKS_INSTALL=PASS', self.output.getvalue())

    def test_resume_corrected_bootstrap_is_accepted(self):
        self.prepare_bootstrap(internal=False)
        INSTALL.main()
        self.assertEqual(len(self.up_definitions), 2)
        self.assertIn('AUDIOBOOKS_INSTALL=PASS', self.output.getvalue())

    def test_resume_refuses_existing_credential_before_docker_mutation(self):
        self.prepare_bootstrap()
        (self.root / 'initial-admin.json').write_text('existing-secret')
        with self.assertRaisesRegex(ValueError, 'not uninitialized bootstrap'):
            INSTALL.main()
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))
        self.assertEqual((self.root / 'initial-admin.json').read_text(), 'existing-secret')

    def test_resume_refuses_completed_install(self):
        self.prepare_bootstrap()
        (self.root / 'installation.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'not uninitialized bootstrap'):
            INSTALL.main()
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_resume_refuses_modified_compose_and_preserves_it(self):
        original = self.prepare_bootstrap()
        changed = original.replace('/audiobooks', '/arbitrary-host-path')
        (self.root / 'compose.yaml').write_text(changed)
        with self.assertRaisesRegex(ValueError, 'unrecognized bootstrap'):
            INSTALL.main()
        self.assertEqual((self.root / 'compose.yaml').read_text(), changed)
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_resume_refuses_insecure_directory_permissions(self):
        self.prepare_bootstrap()
        (self.root / 'config').chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'unsafe bootstrap directory'):
            INSTALL.main()
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_resume_refuses_directory_symlink(self):
        self.prepare_bootstrap()
        (self.root / 'audiobooks').rmdir()
        (self.root / 'audiobooks').symlink_to(self.root / 'metadata', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe bootstrap directory'):
            INSTALL.main()
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_resume_refuses_insecure_compose_permissions(self):
        self.prepare_bootstrap()
        (self.root / 'compose.yaml').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'unsafe bootstrap definition'):
            INSTALL.main()
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_resume_refuses_symlinked_log_without_modifying_target(self):
        self.prepare_bootstrap()
        target = Path(self.temp.name) / 'must-not-overwrite'
        target.write_text('preserve-target')
        (self.root / 'startup.log').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'unsafe bootstrap log'):
            INSTALL.main()
        self.assertEqual(target.read_text(), 'preserve-target')
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_resume_refuses_publicly_readable_log(self):
        self.prepare_bootstrap()
        log = self.root / 'startup.log'
        log.write_text('private-existing-log')
        log.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'unsafe bootstrap log'):
            INSTALL.main()
        self.assertEqual(log.read_text(), 'private-existing-log')
        self.assertFalse(any(call[0] == INSTALL.DOCKER for call in self.calls))

    def test_resume_preserves_existing_private_log_on_success(self):
        self.prepare_bootstrap()
        log = self.root / 'startup.log'
        log.write_text('private-existing-log')
        log.chmod(0o600)
        INSTALL.main()
        self.assertEqual(log.read_text(), 'private-existing-log')
        self.assertNotIn('private-existing-log', self.output.getvalue())

    def test_resume_refuses_changed_image_digest_before_modifying_compose(self):
        original = self.prepare_bootstrap()
        def command(*args):
            if args[1:3] == ('image', 'inspect'):
                changed = 'ghcr.io/advplyr/audiobookshelf@sha256:' + 'b' * 64
                return json.dumps([{'Architecture': 'arm64', 'Os': 'linux', 'RepoDigests': [changed]}])
            return self.command(*args)
        self.run.side_effect = command
        with self.assertRaisesRegex(ValueError, 'immutable image digest unavailable'):
            INSTALL.main()
        self.assertEqual((self.root / 'compose.yaml').read_text(), original)
        self.assertEqual(len(self.up_definitions), 0)

    def test_resume_refuses_initialized_server_without_generating_credentials(self):
        self.prepare_bootstrap()
        self.status.side_effect = [{'isInit': True}]
        with self.assertRaisesRegex(ValueError, 'unexpected initialized state'):
            INSTALL.main()
        self.request.assert_not_called()
        self.assertFalse((self.root / 'initial-admin.json').exists())
        self.assertTrue(any('down' in call for call in self.calls))

    def test_failure_captures_log_privately_before_rollback(self):
        def command(*args):
            if 'logs' in args:
                self.calls.append(args)
                return 'sensitive-local-log'
            return self.command(*args)
        self.run.side_effect = command
        self.request.side_effect = OSError('init failed')
        with self.assertRaises(OSError):
            INSTALL.main()
        log = self.root / 'startup.log'
        self.assertEqual(log.read_text(), 'sensitive-local-log')
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        logs_index = next(i for i, call in enumerate(self.calls) if 'logs' in call)
        down_index = next(i for i, call in enumerate(self.calls) if 'down' in call)
        self.assertLess(logs_index, down_index)
        self.assertNotIn('sensitive-local-log', self.output.getvalue())

    def test_project_conflict_is_refused_before_pull(self):
        def command(*args):
            return 'conflicting-container' if args[1:3] == ('ps', '-aq') else self.command(*args)
        self.run.side_effect = command
        with self.assertRaisesRegex(ValueError, 'project already exists'):
            INSTALL.main()
        self.assertFalse(self.root.exists())
        self.assertFalse(any('pull' in call for call in self.calls))

    def test_port_conflict_is_refused_before_pull(self):
        self.socket.return_value.__enter__.return_value.bind.side_effect = OSError('in use')
        with self.assertRaises(OSError):
            INSTALL.main()
        self.assertFalse(self.root.exists())
        self.assertFalse(any('pull' in call for call in self.calls))

    def test_wrong_architecture_refused_before_data_mutation(self):
        def command(*args):
            if args[1:3] == ('image', 'inspect'):
                return json.dumps([{'Architecture': 'amd64', 'Os': 'linux', 'RepoDigests': [DIGEST]}])
            return self.command(*args)
        self.run.side_effect = command
        with self.assertRaisesRegex(ValueError, 'wrong image architecture'):
            INSTALL.main()
        self.assertFalse(self.root.exists())

    def test_missing_digest_refused_before_data_mutation(self):
        def command(*args):
            if args[1:3] == ('image', 'inspect'):
                return json.dumps([{'Architecture': 'arm64', 'Os': 'linux', 'RepoDigests': []}])
            return self.command(*args)
        self.run.side_effect = command
        with self.assertRaisesRegex(ValueError, 'immutable image digest unavailable'):
            INSTALL.main()
        self.assertFalse(self.root.exists())

    def test_init_failure_rolls_back_only_project_and_preserves_credentials(self):
        self.request.side_effect = OSError('init failed')
        with self.assertRaises(OSError):
            INSTALL.main()
        self.assertEqual(len(self.up_definitions), 1)
        down = [call for call in self.calls if 'down' in call]
        self.assertEqual(len(down), 1)
        self.assertEqual(down[0][-1], 'down')
        self.assertEqual(down[0][3], INSTALL.PROJECT)
        self.assertNotIn('-v', down[0])
        self.assertTrue((self.root / 'initial-admin.json').exists())
        self.assertTrue((self.root / 'config').is_dir())
        self.assertFalse((self.root / 'installation.json').exists())
        self.assertIn('AUDIOBOOKS_ROLLBACK=PASS_DATA_PRESERVED', self.output.getvalue())

    def test_baseline_regression_rolls_back_and_does_not_claim_success(self):
        self.snapshots.side_effect = [dict(BASELINE), {'existing-container': ('restarted', 'healthy')}]
        with self.assertRaisesRegex(ValueError, 'baseline container regression'):
            INSTALL.main()
        self.assertTrue(any('down' in call for call in self.calls))
        self.assertFalse((self.root / 'installation.json').exists())
        self.assertNotIn('AUDIOBOOKS_INSTALL=PASS', self.output.getvalue())
        self.assertTrue((self.root / 'metadata').exists())

    def test_rollback_failure_emits_operator_required(self):
        def command(*args):
            if 'down' in args:
                raise OSError('rollback failed')
            return self.command(*args)
        self.run.side_effect = command
        self.request.side_effect = OSError('init failed')
        with self.assertRaises(OSError):
            INSTALL.main()
        self.assertIn('AUDIOBOOKS_ROLLBACK=FAILED_OPERATOR_REQUIRED', self.output.getvalue())
        self.assertTrue((self.root / 'initial-admin.json').exists())


class AudiobookGatewayBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = REPOSITORY / 'homelab/live/usr/local/sbin/lifeos-deploy-gateway'
        loader = importlib.machinery.SourceFileLoader('audiobook_gateway_under_test', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.gateway = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.gateway)

    def test_fixed_operation_resolves_only_reviewed_wrapper(self):
        self.assertEqual(self.gateway.OPS['install-audiobooks'], {
            'script': 'scripts/lifeos-install-audiobooks.sh', 'privileged': True})
        self.assertEqual(self.gateway.parse_request(['install-audiobooks']), ('install-audiobooks', []))

    def test_fixed_operation_refuses_arguments(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.gateway.parse_request(['install-audiobooks', '/arbitrary/script'])
        self.assertEqual(error.exception.code, 64)


if __name__ == '__main__':
    unittest.main()
