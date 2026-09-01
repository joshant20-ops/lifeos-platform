import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

SOURCE = pathlib.Path('homelab/live/usr/local/sbin/lifeos-job-publisher')


def load_module():
    loader = importlib.machinery.SourceFileLoader('lifeos_job_publisher', str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PublisherFifoTests(unittest.TestCase):
    def setUp(self):
        self.m = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.m.REPO = root
        self.m.STAGING = root / 'jobs/staging'
        self.m.PENDING = root / 'jobs/pending'
        self.m.ARCHIVE = root / 'jobs/archive'
        self.m.RESULTS = root / 'results'
        self.m.STATE_DIR = root / 'state'
        self.m.LOCK = self.m.STATE_DIR / 'publisher.lock'
        self.m.SCRIPT_ROOTS = {
            'diagnostic': root / 'jobs/scripts',
            'control-state': root / 'jobs/change-scripts',
            'root-broker': root / 'jobs/root-scripts',
        }
        for p in [
            self.m.STAGING,
            self.m.PENDING,
            self.m.ARCHIVE,
            self.m.RESULTS,
            root / 'jobs/scripts',
            root / 'jobs/change-scripts',
            root / 'jobs/root-scripts',
        ]:
            p.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def add_job(self, job_id, *, job_type='diagnostic', target='pi5-docker'):
        script_rel = f'jobs/scripts/{job_id}.sh'
        script = self.m.REPO / script_rel
        script.write_text('#!/usr/bin/env bash\nexit 0\n')
        digest = self.m.sha256(script)
        manifest = {
            'schema_version': 1,
            'job_id': job_id,
            'target': target,
            'job_type': job_type,
            'script': script_rel,
            'script_sha256': digest,
            'timeout_seconds': 30,
            'created_by': 'test',
            'description': 'publisher FIFO test',
        }
        path = self.m.STAGING / f'{job_id}.json'
        path.write_text(json.dumps(manifest))
        return path

    def test_invalid_oldest_blocks_later_valid_job(self):
        oldest = self.add_job('0030-oldest', job_type='readonly')
        self.add_job('0031-later')
        promoted = []
        with mock.patch.object(self.m, 'sync_repo'), \
             mock.patch.object(self.m, 'gitleaks', return_value=True), \
             mock.patch.object(self.m, 'promote_one', side_effect=lambda *a: promoted.append(a[1]['job_id'])):
            with self.assertRaises(SystemExit):
                self.m.main()
        self.assertEqual(promoted, [])
        self.assertTrue(oldest.exists())

    def test_existing_pending_same_target_holds_oldest(self):
        self.add_job('0030-oldest')
        pending = self.m.PENDING / '0029-existing.json'
        pending.write_text(json.dumps({'target': 'pi5-docker'}))
        promoted = []
        with mock.patch.object(self.m, 'sync_repo'), \
             mock.patch.object(self.m, 'gitleaks', return_value=True), \
             mock.patch.object(self.m, 'promote_one', side_effect=lambda *a: promoted.append(a[1]['job_id'])):
            rc = self.m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(promoted, [])

    def test_only_oldest_job_promoted_per_run(self):
        self.add_job('0030-oldest')
        self.add_job('0031-later')
        promoted = []
        with mock.patch.object(self.m, 'sync_repo'), \
             mock.patch.object(self.m, 'gitleaks', return_value=True), \
             mock.patch.object(self.m, 'promote_one', side_effect=lambda *a: promoted.append(a[1]['job_id'])):
            rc = self.m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(promoted, ['0030-oldest'])

    def test_script_traversal_cannot_escape_allowed_job_root(self):
        manifest = self.add_job('0030-oldest')
        outside = self.m.REPO / 'jobs/root-scripts/escaped.sh'
        outside.write_text('#!/usr/bin/env bash\nexit 0\n')
        data = json.loads(manifest.read_text())
        data['script'] = 'jobs/scripts/../root-scripts/escaped.sh'
        data['script_sha256'] = self.m.sha256(outside)
        manifest.write_text(json.dumps(data))

        with mock.patch.object(self.m, 'gitleaks', return_value=True):
            with self.assertRaises(SystemExit):
                self.m.validate_manifest(manifest)

    def test_script_symlink_cannot_escape_allowed_job_root(self):
        manifest = self.add_job('0030-oldest')
        outside = self.m.REPO / 'outside.sh'
        outside.write_text('#!/usr/bin/env bash\nexit 0\n')
        script = self.m.REPO / 'jobs/scripts/0030-oldest.sh'
        script.unlink()
        script.symlink_to(outside)
        data = json.loads(manifest.read_text())
        data['script_sha256'] = self.m.sha256(outside)
        manifest.write_text(json.dumps(data))

        with mock.patch.object(self.m, 'gitleaks', return_value=True):
            with self.assertRaises(SystemExit):
                self.m.validate_manifest(manifest)

    def test_root_git_is_pinned_to_repository_owner_and_clean_environment(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(self.m.os, 'geteuid', return_value=0), \
             mock.patch.object(self.m.pwd, 'getpwuid', return_value=mock.Mock(pw_name='root')), \
             mock.patch.object(self.m.subprocess, 'run', return_value=completed) as run:
            self.m.git('fetch', 'origin', 'main')
        command = run.call_args.args[0]
        self.assertEqual(command[:7], [
            '/usr/sbin/runuser', '-u', 'joshan', '--', '/usr/bin/env', '-i', 'HOME=/home/joshan'
        ])
        self.assertIn('PATH=/usr/bin:/bin', command)
        self.assertIn('LANG=C.UTF-8', command)
        self.assertEqual(command[-4:], ['/usr/bin/git', 'fetch', 'origin', 'main'])
        self.assertIsNone(run.call_args.kwargs['env'])

    def test_joshan_git_uses_fixed_home_and_path(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(self.m.os, 'geteuid', return_value=1000), \
             mock.patch.object(self.m.pwd, 'getpwuid', return_value=mock.Mock(pw_name='joshan')), \
             mock.patch.object(self.m.subprocess, 'run', return_value=completed) as run:
            self.m.git('pull', '--ff-only', 'origin', 'main')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/git', 'pull', '--ff-only', 'origin', 'main'])
        self.assertEqual(run.call_args.kwargs['env'], {
            'HOME': '/home/joshan', 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'
        })

    def test_joshan_git_discards_caller_git_and_ssh_environment(self):
        completed = mock.Mock(returncode=0)
        poisoned = {
            'HOME': '/tmp/attacker',
            'PATH': '/tmp/attacker-bin',
            'GIT_DIR': '/tmp/attacker-repo',
            'GIT_WORK_TREE': '/tmp/attacker-tree',
            'GIT_SSH': '/tmp/attacker-ssh',
            'GIT_SSH_COMMAND': 'ssh -o StrictHostKeyChecking=no',
            'SSH_AUTH_SOCK': '/tmp/attacker-agent',
        }
        with mock.patch.dict(self.m.os.environ, poisoned, clear=False), \
             mock.patch.object(self.m.os, 'geteuid', return_value=1000), \
             mock.patch.object(self.m.pwd, 'getpwuid', return_value=mock.Mock(pw_name='joshan')), \
             mock.patch.object(self.m.subprocess, 'run', return_value=completed) as run:
            self.m.git('ls-remote', 'origin', 'refs/heads/main')
        self.assertEqual(run.call_args.kwargs['cwd'], self.m.REPO)
        self.assertEqual(run.call_args.kwargs['env'], {
            'HOME': '/home/joshan', 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'
        })
        self.assertFalse(
            {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_SSH', 'GIT_SSH_COMMAND', 'SSH_AUTH_SOCK'}
            & set(run.call_args.kwargs['env'])
        )

    def test_root_git_discards_caller_environment_and_pins_git_binary(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.dict(self.m.os.environ, {'GIT_SSH_COMMAND': 'false', 'HOME': '/tmp/bad'}), \
             mock.patch.object(self.m.os, 'geteuid', return_value=0), \
             mock.patch.object(self.m.pwd, 'getpwuid', return_value=mock.Mock(pw_name='root')), \
             mock.patch.object(self.m.subprocess, 'run', return_value=completed) as run:
            self.m.git('fetch', 'origin', 'main')
        command = run.call_args.args[0]
        self.assertIn('/usr/bin/env', command)
        self.assertIn('-i', command)
        self.assertEqual(command[-4:], ['/usr/bin/git', 'fetch', 'origin', 'main'])
        self.assertNotIn('GIT_SSH_COMMAND=false', command)

    def test_unexpected_nonroot_identity_fails_closed(self):
        with mock.patch.object(self.m.os, 'geteuid', return_value=2000), \
             mock.patch.object(self.m.pwd, 'getpwuid', return_value=mock.Mock(pw_name='other')), \
             mock.patch.object(self.m.subprocess, 'run') as run:
            with self.assertRaises(SystemExit):
                self.m.git('fetch', 'origin', 'main')
        run.assert_not_called()

    def test_sync_repo_keeps_mandatory_fixed_origin_main_fetch_and_ff_pull(self):
        with mock.patch.object(self.m, 'git') as git:
            self.m.sync_repo()
        self.assertEqual(git.call_args_list, [
            mock.call('fetch', 'origin', 'main'),
            mock.call('pull', '--ff-only', 'origin', 'main'),
        ])


if __name__ == '__main__':
    unittest.main()
