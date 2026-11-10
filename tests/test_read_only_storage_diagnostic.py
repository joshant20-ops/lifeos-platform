"""Tests for the read-only storage diagnostic (#2072)."""
import unittest
from unittest.mock import patch
import subprocess

from governor import read_only_storage_diagnostic as audit


class StorageDiagnosticTests(unittest.TestCase):
    def test_size_buckets(self):
        self.assertEqual(audit.size_bucket(0), "under_1MiB")
        self.assertEqual(audit.size_bucket(1024**3), "1GiB_to_5GiB")
        self.assertEqual(audit.size_bucket(10 * 1024**3), "10GiB_or_more")

    def test_du_timeout_is_sanitised(self):
        with patch.object(audit.Path, "is_dir", return_value=True), \
             patch.object(audit.Path, "is_symlink", return_value=False), \
             patch.object(audit.subprocess, "run", side_effect=subprocess.TimeoutExpired("du", 12)):
            self.assertEqual(audit.bounded_du(audit.ROOT), {"status": "timeout"})

    def test_du_error_does_not_leak_stderr(self):
        fake = subprocess.CompletedProcess(["du"], 1, "", "private path /secret/password")
        with patch.object(audit.Path, "is_dir", return_value=True), \
             patch.object(audit.Path, "is_symlink", return_value=False), \
             patch.object(audit.subprocess, "run", return_value=fake):
            self.assertEqual(audit.bounded_du(audit.ROOT), {"status": "error"})

    def test_du_uses_read_only_fixed_arguments(self):
        fake = subprocess.CompletedProcess(["du"], 0, "4096 /mnt/docker-data/recovery", "")
        with patch.object(audit.Path, "is_dir", return_value=True), \
             patch.object(audit.Path, "is_symlink", return_value=False), \
             patch.object(audit.subprocess, "run", return_value=fake) as run:
            self.assertEqual(audit.bounded_du(audit.ROOT)["status"], "ok")
            args, kwargs = run.call_args
            self.assertEqual(args[0][:4], ["du", "-sx", "--block-size=1", "--"])
            self.assertEqual(kwargs["timeout"], 12)


if __name__ == "__main__":
    unittest.main()
