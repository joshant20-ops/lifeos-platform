import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "governor/paperless_restore.py"
SPEC = importlib.util.spec_from_file_location("paperless_restore", SCRIPT)
restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore)


class PaperlessGovernedRestoreTests(unittest.TestCase):
    def test_recovery_is_preconditioned_and_never_recreates_or_cleans_containers(self):
        source = SCRIPT.read_text()
        self.assertIn('audit.mount_state(path) != "MOUNTED"', source)
        self.assertIn('audit.compose_config_state() != "VALID"', source)
        self.assertIn('audit.resource_state("volume", "paperless_redis_data") != "PRESENT"', source)
        self.assertIn('audit.resource_state("network", "reverse_proxy") != "PRESENT"', source)
        self.assertIn('label=com.docker.compose.project=paperless', source)
        self.assertIn('{{index .Config.Labels "com.docker.compose.service"}}|', source)
        self.assertIn('compose("start", "db", "redis"', source)
        self.assertIn('compose("start", "paperless"', source)
        self.assertNotIn('compose("up"', source)
        self.assertNotIn('compose("pull"', source)
        self.assertNotIn('compose("down"', source)
        self.assertNotIn('compose("rm"', source)
        self.assertNotIn('compose("restart"', source)

    def test_mount_failure_blocks_before_mutation(self):
        original = restore.audit.mount_state
        try:
            restore.audit.mount_state = lambda path: "UNMOUNTED"
            captured = io.StringIO()
            with redirect_stdout(captured):
                result = restore.safe_preflight()
        finally:
            restore.audit.mount_state = original
        self.assertFalse(result)
        self.assertIn("PAPERLESS_RESTORE_BLOCKED=MOUNT_PRECONDITION", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
