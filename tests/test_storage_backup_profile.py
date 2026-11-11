import datetime as dt
import io
import unittest

from scripts.lifeos_storage_backup_profile import profile

ROOT = "/mnt/docker-data/automation/backups/"


class BackupProfileTests(unittest.TestCase):
    def test_group_age_uses_latest_file_and_never_leaks_names(self):
        private = "customer-private-123"
        rows = (f"10\t2026-05-01\t{ROOT}{private}/a\n"
                f"20\t2026-11-01\t{ROOT}{private}/b\n"
                f"50\t2026-05-01\t{ROOT}other-private/c\n").encode()
        result = profile(io.BytesIO(rows), dt.date(2026, 11, 10))
        self.assertEqual(result["backup_groups"], 2)
        self.assertEqual(result["age_bands_by_latest_group_file"]["0-30d"]["bytes"], 30)
        self.assertEqual(result["age_bands_by_latest_group_file"]["181d+"]["bytes"], 50)
        self.assertEqual(result["eligible_for_deletion_bytes"], 0)
        self.assertNotIn(private, str(result))

    def test_producer_hints_require_full_format_and_reconcile_totals(self):
        rows = (f"10\t2026-05-01\t{ROOT}pinned-compose-20260501-120000/a\n"
                f"20\t2026-05-01\t{ROOT}pinned-compose-20260501-120000/b\n"
                f"40\t2026-05-01\t{ROOT}pinned-compose-private/c\n"
                f"50\t2026-05-01\t{ROOT}ha-tower-control-20260501-120000/a\n").encode()
        result = profile(io.BytesIO(rows), dt.date(2026, 11, 10))
        self.assertEqual(result["producer_name_hints"], {
            "pinned-compose": {"groups": 1, "files": 2, "bytes": 30},
            "ha-tower-control": {"groups": 1, "files": 1, "bytes": 50},
            "unknown": {"groups": 1, "files": 1, "bytes": 40},
        })
        self.assertEqual(result["deletion_candidates"], 0)
        self.assertNotIn("pinned-compose-private", str(result))

    def test_flat_files_and_private_repeated_patterns_reconcile(self):
        rows = (f"11\t2026-05-01\t{ROOT}private-flat.tar\n"
                f"20\t2026-05-01\t{ROOT}private-family-20260501-120000/a\n"
                f"30\t2026-05-01\t{ROOT}private-family-20260502-120000/b\n"
                f"40\t2026-05-01\t{ROOT}jobs-exporter-20260501-120000/a\n").encode()
        result = profile(io.BytesIO(rows), dt.date(2026, 11, 10))
        self.assertEqual(result["invalid_rows"], 0)
        self.assertEqual(result["ungrouped_backup_files"], {"files": 1, "bytes": 11})
        self.assertEqual(result["producer_name_hints"]["jobs-exporter"]["bytes"], 40)
        self.assertEqual(result["repeated_unknown_dated_patterns"], 1)
        self.assertEqual(result["largest_unknown_dated_patterns"], [
            {"groups": 2, "files": 2, "bytes": 50},
        ])
        self.assertNotIn("private", str(result))
        self.assertEqual(result["eligible_for_deletion_bytes"], 0)

    def test_invalid_and_outside_root(self):
        rows = (f"4\t2026-05-01\t{ROOT}../escape/file\n"
                "2\t2026-05-01\t/etc/passwd\n"
                f"1\t2027-01-01\t{ROOT}foo/bar\n").encode()
        result = profile(io.BytesIO(rows), dt.date(2026, 11, 10))
        self.assertEqual(result["backup_groups"], 0)
        self.assertEqual(result["invalid_rows"], 2)

    def test_limit(self):
        with self.assertRaisesRegex(ValueError, "inventory_limit_exceeded"):
            profile(io.BytesIO(b"x\n" * 3), dt.date(2026, 11, 10), max_lines=2)


if __name__ == "__main__":
    unittest.main()
