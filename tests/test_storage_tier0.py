import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from governor import storage_tier0 as guard
from scripts.lifeos_storage_retention_inventory import MAX_LINE_BYTES, open_inventory, summarise


class TierZeroTests(unittest.TestCase):
    def test_capacity_does_not_report_underlying_disk_if_mount_is_missing(self):
        with patch.object(guard.Path, "is_mount", return_value=False), \
             patch.object(guard.os, "statvfs") as statvfs:
            self.assertEqual(guard.docker_data_capacity(), {"status": "mount_unverified"})
        statvfs.assert_not_called()

    def test_capacity_reports_aggregate_counters_and_flags_inode_pressure(self):
        stats = SimpleNamespace(f_blocks=100, f_frsize=2**30, f_bavail=15,
                                f_bfree=20, f_files=1000, f_favail=90)
        with patch.object(guard.Path, "is_mount", return_value=True), \
             patch.object(guard.os, "statvfs", return_value=stats):
            report = guard.docker_data_capacity()
            self.assertEqual(report["status"], "below_reserve")
            self.assertEqual(report["used_bytes"], 80 * 2**30)
            self.assertEqual(report["reserved_free_bytes"], 5 * 2**30)
            self.assertEqual(report["available_inodes"], 90)
            stats.f_favail = 100
            self.assertEqual(guard.docker_data_capacity()["status"], "within_reserve")

    def test_healthy_container_cannot_override_network_failure(self):
        with patch.object(guard, "command", side_effect=["true healthy", "000"]), \
             patch.object(guard, "dns_answers", return_value=set()), \
             patch.object(guard, "direct_internet", return_value=False), \
             patch.object(guard, "enough_space", return_value=True):
            report = guard.baseline("192.0.2.1", "example.lan", "192.0.2.2",
                                    "192.0.2.3", "example.test")
        self.assertTrue(report["checks"]["adguard_running"])
        self.assertFalse(report["network_and_capacity_pass"])
        self.assertFalse(report["maintenance_authorised"])
        self.assertNotIn("192.0.2.", str(report))

    def test_passing_network_and_disk_is_evidence_only(self):
        with patch.object(guard, "command", side_effect=["true none", "200"]), \
             patch.object(guard, "dns_answers", return_value={"192.0.2.2"}), \
             patch.object(guard, "direct_internet", return_value=True), \
             patch.object(guard, "enough_space", return_value=True):
            report = guard.baseline("192.0.2.1", "example.lan", "192.0.2.2",
                                    "192.0.2.3", "example.test")
        self.assertTrue(report["network_and_capacity_pass"])
        self.assertFalse(report["maintenance_authorised"])

    def test_inventory_refuses_symlinks_and_oversize_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inventory"
            path.symlink_to("/dev/null")
            with self.assertRaises(OSError):
                with open_inventory(path):
                    self.fail("symlink accepted")
        with self.assertRaisesRegex(ValueError, "inventory_line_limit_exceeded"):
            summarise(io.BytesIO(b"x" * (MAX_LINE_BYTES + 1)), None)

    def test_inventory_rejects_concurrent_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inventory"
            path.write_bytes(b"initial")
            with self.assertRaisesRegex(ValueError, "inventory_changed_during_read"):
                with open_inventory(path) as stream:
                    self.assertEqual(stream.read(), b"initial")
                    path.write_bytes(b"changed length")
