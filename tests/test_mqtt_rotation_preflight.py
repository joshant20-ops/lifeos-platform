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
            checks, size = probe.preflight()
        self.assertFalse(any(checks.values()))
        self.assertIsNone(size)
