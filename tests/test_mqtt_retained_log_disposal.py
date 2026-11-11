from pathlib import Path
import tempfile
import unittest

from governor.mqtt_retained_log_archive import ArchiveUnverified, fingerprint
from governor.mqtt_retained_log_disposal import reclaim_batches


class RetainedLogDisposalTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "closed.log"
        journal = Path(directory.name) / "journal"
        journal.mkdir()
        path.write_bytes(b"alpha\nbeta\ngamma\n")
        info = path.stat()
        return path, journal, {"fingerprint": list(fingerprint(info)),
                               "allocated_bytes": info.st_blocks * 512}

    def test_requires_fresh_backup_readback(self):
        path, journal, proof = self.fixture()
        def unexpected(_):
            self.fail("inference should not run when NAS readback fails")
        with self.assertRaisesRegex(ArchiveUnverified, "fresh_nas"):
            reclaim_batches(path, journal, proof, lambda: None, lambda _: False,
                            lambda _: True, unexpected, batch_bytes=6)
        self.assertEqual(path.read_bytes(), b"alpha\nbeta\ngamma\n")

    def test_reclaims_successful_tail_batch_and_resumes_after_model_failure(self):
        path, journal, proof = self.fixture()
        unrelated = path.with_name("active.log")
        unrelated.write_bytes(b"active")
        calls = []
        progress = []

        def inference(evidence):
            calls.append((evidence["start_offset"], evidence["end_offset"]))
            if calls == [(11, 17), (6, 11)]:
                raise ArchiveUnverified("model_failed")
            return {"provider": "ollama", "summary": "synthetic", "findings": []}

        def run():
            return reclaim_batches(path, journal, proof, lambda: None, lambda _: True,
                                   lambda _: True, inference, progress.append, batch_bytes=6)

        with self.assertRaisesRegex(ArchiveUnverified, "model_failed"):
            run()
        self.assertEqual(path.read_bytes(), b"alpha\nbeta\n")
        self.assertEqual(progress[0]["remaining_bytes"], 11)
        result = run()
        self.assertEqual(calls, [(11, 17), (6, 11), (6, 11), (0, 6)])
        self.assertEqual(result["batches_reclaimed"], 3)
        self.assertEqual(result["remaining_bytes"], 0)
        self.assertEqual(result["allocated_bytes_removed"], proof["allocated_bytes"])
        self.assertEqual(unrelated.read_bytes(), b"active")

    def test_inode_change_blocks_before_review(self):
        path, journal, proof = self.fixture()
        path.write_bytes(b"unexpected data\n")
        with self.assertRaisesRegex(ArchiveUnverified, "approved_inode_changed"):
            reclaim_batches(path, journal, proof, lambda: None, lambda _: True,
                            lambda _: True, lambda _: {"provider": "ollama"}, batch_bytes=6)
        self.assertEqual(path.read_bytes(), b"unexpected data\n")
