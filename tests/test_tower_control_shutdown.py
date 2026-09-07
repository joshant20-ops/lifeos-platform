import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "governor" / "tower_control.py"
spec = importlib.util.spec_from_file_location("tower_control", MODULE_PATH)
tower_control = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tower_control)


class TowerShutdownTests(unittest.TestCase):
    def test_graceful_shutdown_reuses_service_account_identity(self):
        cfg = {
            "host": "tower.invalid",
            "shutdown": {"type": "linux_ssh", "user": "joshan"},
        }
        with mock.patch.object(tower_control, "run") as run:
            tower_control.graceful_shutdown(cfg)
        args = list(run.call_args.args)
        self.assertEqual(args[0], "ssh")
        self.assertNotIn("-i", args)
        self.assertIn("IdentitiesOnly=no", args)
        self.assertEqual(args[-2:], ["joshan@tower.invalid", "sudo -n /sbin/poweroff"])
        self.assertEqual(run.call_args.kwargs, {"check": True, "timeout": 20})


    def test_graceful_shutdown_rejects_missing_endpoint(self):
        with self.assertRaisesRegex(RuntimeError, "Tower shutdown SSH endpoint is incomplete"):
            tower_control.graceful_shutdown({"shutdown": {"type": "linux_ssh"}})

    def test_compute_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir, old_state = tower_control.STATE_DIR, tower_control.COMPUTE_STATE
            try:
                tower_control.STATE_DIR = pathlib.Path(tmp)
                tower_control.COMPUTE_STATE = pathlib.Path(tmp) / "compute-lifecycle.json"
                tower_control._save_compute_state({"woke_by_lifeos": True})
                self.assertEqual(tower_control._load_compute_state(), {"woke_by_lifeos": True})
            finally:
                tower_control.STATE_DIR, tower_control.COMPUTE_STATE = old_dir, old_state


if __name__ == "__main__":
    unittest.main()
