import datetime as dt
import io
import unittest

from scripts.lifeos_storage_retention_inventory import classify, summarise


class StorageInventoryTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify("queues/closed_loop/abc"), "queues/closed_loop")
        self.assertEqual(classify("logs/cron/foo"), "logs/cron")
        self.assertEqual(classify("backups/example/file"), "backups")

    def test_aggregate_no_paths_and_no_deletion(self):
        private = "/mnt/docker-data/automation/backups/private-name/token.json"
        data = ("123\\t2026-05-01\\t" + private + "\\n").replace("\\t", "\t").replace("\\n", "\n").encode()
        result = summarise(io.BytesIO(data), dt.date(2026, 11, 10))
        self.assertEqual(result["categories"]["backups"]["bytes"], 123)
        self.assertEqual(result["eligible_for_deletion_bytes"], 0)
        self.assertNotIn("private-name", str(result))
        self.assertEqual(result["categories"]["backups"]["older_than_90d_files"], 1)

    def test_bad_rows_fail_closed(self):
        result = summarise(io.BytesIO(b"123\t2026-01-01\t/etc/shadow\n"), dt.date(2026, 11, 10))
        self.assertEqual(result["invalid_rows"], 1)
        self.assertEqual(result["categories"], {})

    def test_limit(self):
        with self.assertRaisesRegex(ValueError, "inventory_limit_exceeded"):
            summarise(io.BytesIO(b"x\n" * 3), dt.date(2026, 11, 10), max_lines=2)


if __name__ == "__main__":
    unittest.main()
