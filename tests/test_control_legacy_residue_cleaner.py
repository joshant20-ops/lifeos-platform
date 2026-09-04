import subprocess
import unittest
from pathlib import Path

SCRIPT = Path('scripts/clean-lifeos-control-legacy-executable-residue.sh')
TEXT = SCRIPT.read_text()


class ControlLegacyResidueCleanerTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp = subprocess.run(['bash', '-n', str(SCRIPT)], text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_exact_old_source_blobs_are_pinned(self):
        for blob in (
            '225c61b81452eee6924039e1ab24578f84e966a3',
            'f5e0ca0e76a348f76e2325c23e3c92273ee8be25',
            '127180b1376af17bda759e24f6b0949d93381726',
        ):
            self.assertIn(blob, TEXT)
        self.assertIn('git hash-object "$path"', TEXT)

    def test_only_expected_residue_and_pycache_are_permitted(self):
        self.assertIn('broker/lifeos-root-broker', TEXT)
        self.assertIn('publisher/lifeos-job-publisher', TEXT)
        self.assertIn('runner/lifeos-pi-control-runner', TEXT)
        self.assertIn('broker/__pycache__/*.pyc', TEXT)
        self.assertIn('unexpected legacy residue path', TEXT)
        self.assertIn('symlink not permitted in legacy residue', TEXT)

    def test_backup_and_checksums_precede_delete(self):
        self.assertIn('legacy-executable-residue.tar', TEXT)
        self.assertIn('legacy-executable-residue.sha256', TEXT)
        self.assertLess(TEXT.index('tar -C "$CONTROL"'), TEXT.index('rm -rf "$CONTROL/broker"'))
        self.assertLess(TEXT.index('sha256sum "$TAR"'), TEXT.index('rm -rf "$CONTROL/broker"'))

    def test_runtime_paths_are_not_deleted(self):
        self.assertNotIn('rm -rf "$CONTROL/jobs', TEXT)
        self.assertNotIn('rm -rf "$CONTROL/results', TEXT)
        self.assertNotIn('rm -rf "$CONTROL/state', TEXT)

    def test_unexpected_untracked_content_still_fails_closed(self):
        self.assertIn('unexpected untracked control file outside legacy residue', TEXT)
        self.assertIn('unexpected untracked control file remains', TEXT)

    def test_machine_readable_completion(self):
        self.assertIn("CLEANER_STATUS=PASS", TEXT)
        self.assertIn("NEXT_REQUIRED=run_control_runtime_ownership_migration", TEXT)


if __name__ == '__main__':
    unittest.main()
