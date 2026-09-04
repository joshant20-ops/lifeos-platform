import subprocess
import unittest
from pathlib import Path

SCRIPT = Path('scripts/rehydrate-stale-activation-and-migrate.sh')
TEXT = SCRIPT.read_text()


class HistoricalStaleActivationWrapperTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp = subprocess.run(['bash', '-n', str(SCRIPT)], text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_historical_evidence_is_pinned(self):
        self.assertIn('29bf111d4021fe9eb9f5e6c0e409c039167b1fdd', TEXT)
        self.assertIn('bd24600e7abfda6e18bbd725fe0f9814a575795e8748b38951c2bb6eb85c6878', TEXT)
        self.assertIn('historical-manifest.json', TEXT)
        self.assertIn('historical-script.sh', TEXT)
        self.assertIn('historical.sha256', TEXT)

    def test_rehydrate_only_when_live_state_absent(self):
        self.assertIn('manifest/script/result/archive all absent', TEXT)
        self.assertIn('stale activation is already quarantined; do not rehydrate again', TEXT)

    def test_writers_are_stopped_before_rehydrate(self):
        stop_idx = TEXT.index("CONTROL_WRITERS=QUIESCED")
        rehydrate_idx = TEXT.index('install -m 0640 "$EVIDENCE_DIR/historical-manifest.json"')
        self.assertLess(stop_idx, rehydrate_idx)
        self.assertIn("pgrep -af 'lifeos-(job-publisher|pi-control-runner)'", TEXT)
        self.assertIn('publisher.lock', TEXT)
        self.assertIn('runner.lock', TEXT)

    def test_stale_job_is_never_executed(self):
        self.assertNotIn('bash "$script"', TEXT)
        self.assertNotIn('lifeos-root-broker.sock', TEXT)
        self.assertIn("STALE_ACTIVATION_REHYDRATED=PASS writers=stopped", TEXT)
        self.assertIn('MIGRATION_CHAIN=START', TEXT)

    def test_failure_after_quiesce_leaves_writers_stopped(self):
        self.assertIn('CONTROL_WRITERS_LEFT_STOPPED=YES', TEXT)
        self.assertIn('if (( MIGRATION_RC != 0 )); then', TEXT)
        self.assertNotIn('if (( MIGRATION_RC != 0 )); then\n  restore_writers', TEXT)

    def test_success_requires_quarantine_then_restores_writers(self):
        self.assertIn('quarantined stale activation evidence missing after migration', TEXT)
        verify_idx = TEXT.index('quarantined stale activation evidence missing after migration')
        restore_idx = TEXT.index('restore_writers', verify_idx)
        self.assertLess(verify_idx, restore_idx)
        self.assertIn('WRAPPER_STATUS=PASS', TEXT)
        self.assertIn('NEXT_REQUIRED=fresh_engineer_activation_from_live_evidence', TEXT)


if __name__ == '__main__':
    unittest.main()
