import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('producer', ROOT/'governor/backup_producer_metadata.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'lifeos-adapt-ha-tower-control.sh'; self.source.write_text('# synthetic producer')
        self.backups = self.root/'backups'; self.backups.mkdir()
        self.g = self.backups/'ha-tower-control-synthetic'; self.g.mkdir()
        (self.g/'config.before').write_text('synthetic')

    def test_success_receipt_not_recovery_verification(self):
        m.begin(self.g, self.source); m.finish(self.g, 0)
        r = m.read_receipt(self.g)
        self.assertEqual(r['state'], 'completed'); self.assertIsNotNone(r['completed_at'])
        self.assertEqual(r['verification'], 'unverified'); self.assertFalse(r['references_verified'])

    def test_interruption_remains_active(self):
        m.begin(self.g, self.source)
        r = m.read_receipt(self.g); self.assertEqual(r['state'], 'active'); self.assertIsNone(r['completed_at'])

    def test_failed_receipt(self):
        m.begin(self.g, self.source); m.finish(self.g, 7)
        self.assertEqual(m.read_receipt(self.g)['state'], 'failed')

    def test_collision_preserves_original(self):
        m.begin(self.g, self.source); before = (self.g/m.RECEIPT).read_bytes()
        with self.assertRaises(FileExistsError): m.begin(self.g, self.source)
        self.assertEqual(before, (self.g/m.RECEIPT).read_bytes())

    def test_duplicate_finalize_refused(self):
        m.begin(self.g, self.source); m.finish(self.g, 0)
        with self.assertRaises(ValueError): m.finish(self.g, 0)

    def test_symlink_generation_refused(self):
        link = self.backups/'ha-tower-control-link'; link.symlink_to(self.g)
        with self.assertRaises(ValueError): m.begin(link, self.source)

    def test_unknown_producer_refused(self):
        source = self.root/'unknown.sh'; source.write_text('synthetic')
        with self.assertRaises(ValueError): m.begin(self.g, source)

    def test_receipt_is_private(self):
        m.begin(self.g, self.source)
        self.assertEqual((self.g/m.RECEIPT).stat().st_mode & 0o777, 0o600)

    def test_legacy_old_name_never_becomes_eligible(self):
        self.g.rename(self.backups/'ha-tower-control-20000101-000000')
        r = m.discover(self.backups)
        self.assertEqual(r['counts']['missing_completion_evidence'], 1)
        self.assertIsNone(r['eligible_generations'])
        self.assertEqual(r['verified_eligible_generations'], 0)

    def test_measurement_without_evidence_mutation(self):
        before = (self.g/'config.before').stat(); r = m.discover(self.backups)
        after = (self.g/'config.before').stat()
        self.assertEqual(r['measured_logical_bytes'], len('synthetic'))
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertEqual(r['measured_allocated_file_bytes'], before.st_blocks * 512)
        self.assertFalse((self.g/m.RECEIPT).exists())

    def test_summary_does_not_expose_generation_or_payload(self):
        r = json.dumps(m.discover(self.backups))
        self.assertNotIn(self.g.name, r); self.assertNotIn('config.before', r)

    def test_hardlink_held(self):
        os.link(self.g/'config.before', self.g/'linked')
        self.assertEqual(m.discover(self.backups)['counts']['unmeasured_hold'], 1)

    def test_symlink_tree_held(self):
        (self.g/'link').symlink_to(self.source)
        self.assertEqual(m.discover(self.backups)['counts']['unmeasured_hold'], 1)

    def test_entry_bound(self):
        self.assertEqual(m.discover(self.backups, limit=0)['counts']['entry_limit_reached'], 1)

    def test_permission_error_never_reports_measured_size(self):
        def denied(*args, **kwargs):
            kwargs['onerror'](PermissionError('synthetic'))
        with patch.object(m.os, 'walk', side_effect=denied):
            summary = m.discover(self.backups)
        self.assertEqual(summary['counts']['unmeasured_hold'], 1)
        self.assertEqual(summary['counts'].get('size_verified_generations', 0), 0)

    def test_invalid_receipt_held(self):
        (self.g/m.RECEIPT).write_text('not-json')
        self.assertEqual(m.discover(self.backups)['counts']['invalid_receipt_hold'], 1)

    def test_wrong_receipt_json_type_held(self):
        (self.g/m.RECEIPT).write_text('[]')
        self.assertEqual(m.discover(self.backups)['counts']['invalid_receipt_hold'], 1)

    def test_private_records_retain_exact_identity_and_hold(self):
        records = []; m.discover(self.backups, private_records=records)
        self.assertEqual(records[0]['generation_id'], self.g.name)
        self.assertEqual(records[0]['deletion_disposition'], 'HOLD')
        self.assertEqual(records[0]['logical_bytes'], len('synthetic'))

    def test_native_receipt_normalizes_to_existing_retention_hold(self):
        m.begin(self.g, self.source); m.finish(self.g, 0)
        normalized = []; m.discover(self.backups, normalized=normalized)
        self.assertEqual(len(normalized), 1)
        g = normalized[0]
        self.assertFalse(g['timestamp_verified']); self.assertFalse(g['references_verified'])
        self.assertEqual(g['verification'], 'unverified')
        self.assertEqual(g['logical_bytes'], sum(f['identity']['st_size'] for f in g['files']))
        self.assertEqual(g['allocated_bytes'], sum(f['allocated_bytes'] for f in g['files']))

    def test_forged_verification_flags_not_trusted(self):
        m.begin(self.g, self.source); m.finish(self.g, 0)
        receipt = m.read_receipt(self.g); receipt.update(verification='passed', references_verified=True, timestamp_verified=True)
        g = m.retention_generation(receipt, self.g.name, [], True)
        self.assertFalse(g['references_verified']); self.assertFalse(g['timestamp_verified'])
        self.assertEqual(g['verification'], 'unverified')

    def test_exit_hook_preserves_failure_after_err_handler(self):
        source = (ROOT/'scripts/lifeos-adapt-ha-tower-control.sh').read_text()
        hook = source.split('# Producer receipt is lifecycle evidence only; recovery/reference holds remain.')[1].split('\nfi\n', 1)[0]+'\nfi\n'
        # Exercise the exact shell hook with only synthetic data, never producer operations.
        hook = hook.replace('"$(dirname -- "${BASH_SOURCE[0]}")/../governor/backup_producer_metadata.py"', '"'+str(ROOT/'governor/backup_producer_metadata.py')+'"')
        self.source.write_text('set -Eeuo pipefail\nBACKUP="$1"\ntrap \'exit 7\' ERR\n'+hook+'false\n')
        result = subprocess.run(['bash', str(self.source), str(self.g)], capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(m.read_receipt(self.g)['state'], 'failed')

    def test_receipt_failure_does_not_trigger_production_rollback(self):
        source = (ROOT/'scripts/lifeos-adapt-ha-tower-control.sh').read_text()
        hook = source.split('# Producer receipt is lifecycle evidence only; recovery/reference holds remain.')[1].split('\nfi\n', 1)[0]+'\nfi\n'
        hook = hook.replace('"$(dirname -- "${BASH_SOURCE[0]}")/../governor/backup_producer_metadata.py"', '"/nonexistent/metadata-helper"')
        self.source.write_text('set -Eeuo pipefail\nBACKUP="$1"\ntrap \'exit 99\' ERR\n'+hook+'exit 0\n')
        result = subprocess.run(['bash', str(self.source), str(self.g)], capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_all_native_producers_use_receipt_without_replacing_err_trap(self):
        for name in m.PRODUCERS:
            text = (ROOT/'scripts'/name).read_text()
            self.assertIn('trap ', text); self.assertIn(' ERR', text)
            self.assertIn(' EXIT', text); self.assertIn(' begin "$BACKUP"', text)
            subprocess.run(['bash', '-n', str(ROOT/'scripts'/name)], check=True)


if __name__ == '__main__': unittest.main()
