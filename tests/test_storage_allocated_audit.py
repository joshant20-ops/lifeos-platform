from pathlib import Path
import unittest

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
