import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import lifeos_storage_allocated_audit as audit
from scripts.lifeos_storage_allocated_audit import summarize


class AllocatedAuditTests(unittest.TestCase):
    def test_total_keeps_private_names_out_of_output(self):
        result = summarize(b"4096\t/mount/automation\0"
                           b"4096\t/mount/private-sibling\0"
                           b"12288\t/mount\0",
                           Path("/mount"), True, 16000, 16384)
        self.assertTrue(result["scan_complete"])
        self.assertEqual(result["used_minus_visible_bytes"], 4096)
        self.assertEqual(result["allocated_bytes_by_category"], {
            "automation": 4096, "other_entries": 4096, "mount_root_and_loose_files": 4096,
        })
        self.assertNotIn("private-sibling", str(result))

    def test_interrupted_scan_uses_only_complete_records(self):
        result = summarize(b"4096\t/mount/automation\0" b"12\t/mount/incomplete",
                           Path("/mount"), False, 16384, 16384)
        self.assertFalse(result["scan_complete"])
        self.assertEqual(result["visible_allocated_bytes"], 4096)

    def test_unreadable_mount_is_reported_without_attempting_du(self):
        with patch.object(audit.os, "scandir", side_effect=PermissionError("private name")), \
             patch.object(audit.subprocess, "run") as run:
            self.assertEqual(audit.scan(Path("/mount")), (b"", "root_listing_denied"))
        run.assert_not_called()

    def test_du_timeout_keeps_partial_output(self):
        with tempfile.TemporaryDirectory() as root, \
             patch.object(audit.subprocess, "run", side_effect=subprocess.TimeoutExpired(
                 ["/usr/bin/du"], 50, output=b"4096\t/mount/automation\0")):
            self.assertEqual(audit.scan(Path(root)), (b"4096\t/mount/automation\0", "du_timeout"))

    def test_partial_measurement_fails_and_keeps_filesystem_counters(self):
        blocks = {"capacity_bytes": 100 * 2**30, "used_bytes": 70 * 2**30,
                  "reserved_free_bytes": 5 * 2**30, "available_bytes": 25 * 2**30,
                  "available_inodes": 1000}
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as root, \
             patch.object(audit, "ROOT", Path(root)), \
             patch.object(audit, "mount_scope_safe", return_value=True), \
             patch.object(audit, "storage_blocks", return_value=blocks), \
             patch.object(audit.os, "statvfs") as statvfs, \
             patch.object(audit, "scan", return_value=(b"", "du_failed")), \
             contextlib.redirect_stdout(output):
            statvfs.return_value.f_files = 1000
            self.assertEqual(audit.main(), 2)
        report = json.loads(output.getvalue())
        self.assertEqual(report["scan_status"], "du_failed")
        self.assertFalse(report["scan_complete"])
        self.assertEqual(report["filesystem_blocks_after"], blocks)
