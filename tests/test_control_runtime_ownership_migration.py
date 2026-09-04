import subprocess
import unittest
from pathlib import Path

SCRIPT = Path('scripts/migrate-lifeos-control-runtime-ownership.sh')
TEXT = SCRIPT.read_text()


class ControlRuntimeOwnershipMigrationTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp = subprocess.run(['bash', '-n', str(SCRIPT)], text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_pins_required_migration_commits(self):
        self.assertIn('fae946238b9c32da7c15fd8e271008330a3a4196', TEXT)
        self.assertIn('f774fb6ef4c9bef431803d60ed4e0abb6f0ecf2a', TEXT)

    def test_preserves_all_runtime_owned_paths_before_mutation(self):
        for token in (
            'jobs/staging', 'jobs/staged', 'jobs/pending', 'jobs/archive',
            'jobs/scripts', 'jobs/change-scripts', 'jobs/root-scripts',
            'results', 'state', 'runtime.tar', 'runtime.sha256',
        ):
            self.assertIn(token, TEXT)
        self.assertLess(TEXT.index("stage 5 'PRESERVE ALL RUNTIME STATE'"),
                        TEXT.index("stage 6 'MIGRATE GIT OWNERSHIP AND RESTORE RUNTIME BYTES'"))

    def test_has_fail_closed_rollback_and_writer_quiesce(self):
        for token in (
            'ROLLBACK=START', 'reset --hard "$OLD_HEAD"',
            'lifeos-control-job-submit.socket', 'publisher.lock', 'runner.lock',
            "pgrep -af 'lifeos-(job-publisher|pi-control-runner)'",
        ):
            self.assertIn(token, TEXT)

    def test_stale_activation_is_quarantined_not_executed(self):
        self.assertIn('QUARANTINE OBSOLETE ACTIVATION WITHOUT CONSUMING IT', TEXT)
        self.assertIn('QUARANTINED_SUPERSEDED', TEXT)
        self.assertIn('assured root-broker bytes no longer match canonical main', TEXT)
        self.assertNotIn('"$RUNNER" >', TEXT)
        self.assertNotIn('EXECUTE ACCEPTED ACTIVATION', TEXT)

    def test_installs_only_pinned_safe_publisher_and_runner(self):
        self.assertIn('git -C "$PLATFORM" show "$SAFE_PLATFORM_COMMIT:homelab/live/usr/local/sbin/lifeos-job-publisher"', TEXT)
        self.assertIn('git -C "$PLATFORM" show "$SAFE_PLATFORM_COMMIT:homelab/live/usr/local/sbin/lifeos-pi-control-runner"', TEXT)
        self.assertIn('"persistence": "local-runtime"', TEXT)
        self.assertIn('+refs/heads/main:refs/remotes/origin/main', TEXT)

    def test_emits_machine_readable_stage_and_next_action_evidence(self):
        self.assertIn("STAGE_%s=PASS", TEXT)
        self.assertIn("STAGE_%s=FAIL", TEXT)
        self.assertIn('FINAL_STATUS=PASS', TEXT)
        self.assertIn('NEXT_REQUIRED=fresh_engineer_activation_from_live_evidence', TEXT)
        self.assertIn('LIVE_ROOT_BROKER_SHA256=', TEXT)
        self.assertIn('CANONICAL_ROOT_BROKER_SHA256=', TEXT)


if __name__ == '__main__':
    unittest.main()
