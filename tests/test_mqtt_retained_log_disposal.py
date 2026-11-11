from pathlib import Path
import tempfile
import unittest

from governor.mqtt_retained_log_archive import ArchiveUnverified, fingerprint
from governor.mqtt_retained_log_disposal import reclaim_one


class RetainedLogDisposalTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "closed.log"
        journal = Path(directory.name) / "journal"
        journal.mkdir()
        path.write_bytes(b"synthetic retained data")
        info = path.stat()
        return path, journal, {"fingerprint": fingerprint(info),
                               "allocated_bytes": info.st_blocks * 512,
                               "archive_tag": "synthetic"}

    def test_requires_fresh_backup_readback(self):
        path, journal, proof = self.fixture()
        with self.assertRaisesRegex(ArchiveUnverified, "fresh_nas"):
            reclaim_one(path, journal, proof, lambda: None, lambda _: False, lambda _: True)
        self.assertTrue(path.is_file())

    def test_quarantine_preserves_inode_if_final_guard_fails(self):
        path, journal, proof = self.fixture()

        def guard():
            if not path.exists():
                raise ArchiveUnverified("outage")

        with self.assertRaisesRegex(ArchiveUnverified, "outage"):
            reclaim_one(path, journal, proof, guard, lambda _: True, lambda _: True)
        retained, = path.parent.glob(".lifeos-mqtt-disposal-*/retained.log")
        self.assertEqual(retained.read_bytes(), b"synthetic retained data")
        self.assertFalse((journal / "disposal-complete.json").exists())

    def test_removes_only_verified_fixture(self):
        path, journal, proof = self.fixture()
        unrelated = path.with_name("active.log")
        unrelated.write_bytes(b"active")
        reclaimed = reclaim_one(path, journal, proof, lambda: None, lambda _: True, lambda _: True)
        self.assertEqual(reclaimed, proof["allocated_bytes"])
        self.assertFalse(path.exists())
        self.assertEqual(unrelated.read_bytes(), b"active")
