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


if __name__ == '__main__':
    unittest.main()
