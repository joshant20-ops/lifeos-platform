"""Contracts for the isolated EmailOps shadow boundary."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from governor import emailops_runtime_audit as audit

ROOT = Path(__file__).resolve().parents[1]


class EmailOpsShadowTests(unittest.TestCase):
    def test_pin_is_exact_and_mailbox_writes_are_disabled(self):
        pin = json.loads((ROOT / "config/emailops-upstream.json").read_text())
        self.assertRegex(pin["commit"], r"^[a-f0-9]{40}$")
        self.assertRegex(pin["archive_sha256"], r"^[a-f0-9]{64}$")
        self.assertFalse(pin["mailbox_writes"])
        self.assertEqual(pin["mode"], "shadow")

    def test_audit_does_not_expose_probe_output_or_access_credentials(self):
        import subprocess
        private = "PRIVATE_SENTINEL_DO_NOT_LOG"
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(audit, "PROFILE", Path(directory)), \
             patch.object(audit.shutil, "which", return_value="/usr/bin/busctl"), \
             patch.object(audit, "probe_command", return_value=subprocess.CompletedProcess([], 0, private, private)), \
             patch.object(audit.shutil, "disk_usage", return_value=type("Usage", (), {"free": 1000000})()):
            result = audit.audit()
        self.assertNotIn(private, str(result))
        self.assertEqual(result["EMAILOPS_SECRET_SERVICE"], "NOT_ACTIVE")
        self.assertEqual(result["EMAILOPS_MAILBOX_WRITES"], "DISABLED")

    def test_wrong_runtime_is_blocked_before_probing(self):
        with patch.object(audit.platform, "node", return_value="cloud"), patch.object(audit, "audit") as probe:
            self.assertEqual(audit.main(), 20)
        probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
