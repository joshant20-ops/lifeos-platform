import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from governor import mqtt_rotation_preflight as probe


class PreflightTests(unittest.TestCase):
    def test_writer_proof_matches_open_inode_and_access_mode(self):
        with tempfile.TemporaryDirectory() as root:
            log = Path(root) / "test.log"
            with log.open("w") as writer, log.open("r") as reader:
                self.assertTrue(probe.writer_matches(probe.os.getpid(), log.stat()))
            with log.open("r"):
                self.assertFalse(probe.writer_matches(probe.os.getpid(), log.stat()))

    def test_unavailable_inspect_fails_closed(self):
        with patch.object(probe, "command", return_value=""):
            checks, size, writer_status = probe.preflight()
        self.assertFalse(any(checks.values()))
        self.assertIsNone(size)

    def test_denied_writer_access_does_not_skip_identity_check(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "test.log"
            path.touch()
            broker = {"Id": "broker", "Image": "image",
                      "State": {"Pid": 123, "Running": True, "StartedAt": "test",
                                "Health": {"Status": "healthy"}},
                      "Mounts": [{"Destination": "/mosquitto/log", "Source": root,
                                  "Type": "bind", "RW": True}]}
            image = {"Architecture": "arm64", "RepoDigests": [probe.IMAGE]}
            with patch.object(probe, "LOG", path), \
                 patch.object(probe, "inspect", side_effect=[broker, image, broker]), \
                 patch.object(probe, "writer_matches", side_effect=PermissionError):
                checks, _, status = probe.preflight()
            self.assertTrue(checks["stable_identity"])
            self.assertFalse(checks["confirmed_writer"])
            self.assertEqual(status, "permission_denied")
