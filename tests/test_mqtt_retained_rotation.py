from pathlib import Path
import tempfile
import unittest

from governor.mqtt_retained_rotation import RotationStopped, rotate


class RetainedRotationTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        directory = Path(temp.name)
        journal = directory / "journal"
        journal.mkdir(mode=0o700)
        (directory / "active.log").write_bytes(b"required historical evidence")
        return directory, journal

    def test_reopens_and_retains_every_old_byte(self):
        directory, journal = self.fixture()
        old_bytes = (directory / "active.log").read_bytes()
        def reopen():
            (directory / "active.log").write_bytes(b"new message")
        def verify(old, new):
            self.assertNotEqual(old.st_ino, new.st_ino)
            self.assertEqual((directory / "retained.log").read_bytes(), old_bytes)
        report = rotate(directory, "active.log", "retained.log", journal,
                        lambda: None, lambda info: True, reopen, verify)
        self.assertEqual(report["reclaimed_bytes"], 0)
        self.assertTrue((journal / "verified.json").exists())

    def test_outage_before_rename_leaves_log_untouched(self):
        directory, journal = self.fixture()
        def offline():
            raise RotationStopped("dns_unavailable")
        with self.assertRaisesRegex(RotationStopped, "dns_unavailable"):
            rotate(directory, "active.log", "retained.log", journal,
                   offline, lambda info: True, lambda: None, lambda old, new: None)
        self.assertFalse((directory / "retained.log").exists())

    def test_failed_reopen_restores_name_without_removing_evidence(self):
        directory, journal = self.fixture()
        def fail():
            raise RotationStopped("reopen_failed")
        with self.assertRaises(RotationStopped):
            rotate(directory, "active.log", "retained.log", journal,
                   lambda: None, lambda info: True, fail, lambda old, new: None)
        self.assertEqual((directory / "active.log").read_bytes(), b"required historical evidence")
        self.assertTrue((journal / "name_restored.json").exists())

    def test_failure_with_new_file_preserves_both(self):
        directory, journal = self.fixture()
        def reopen():
            (directory / "active.log").write_bytes(b"new")
        def fail(old, new):
            raise RotationStopped("continuity_failed")
        with self.assertRaises(RotationStopped):
            rotate(directory, "active.log", "retained.log", journal,
                   lambda: None, lambda info: True, reopen, fail)
        self.assertEqual((directory / "active.log").read_bytes(), b"new")
        self.assertEqual((directory / "retained.log").read_bytes(), b"required historical evidence")

    def test_existing_retained_path_and_symlink_are_rejected(self):
        directory, journal = self.fixture()
        (directory / "retained.log").write_bytes(b"older evidence")
        with self.assertRaises(FileExistsError):
            rotate(directory, "active.log", "retained.log", journal,
                   lambda: None, lambda info: True, lambda: None, lambda old, new: None)
        self.assertEqual((directory / "retained.log").read_bytes(), b"older evidence")
        (directory / "active.log").unlink()
        (directory / "active.log").symlink_to(directory / "retained.log")
        with self.assertRaises(RotationStopped):
            rotate(directory, "active.log", "other.log", journal,
                   lambda: None, lambda info: True, lambda: None, lambda old, new: None)

    def test_disk_or_permission_failure_before_journal_blocks_mutation(self):
        directory, journal = self.fixture()
        with self.assertRaises(FileNotFoundError):
            rotate(directory, "active.log", "retained.log", journal / "missing",
                   lambda: None, lambda info: True, lambda: None, lambda old, new: None)
        self.assertFalse((directory / "retained.log").exists())

    def test_same_journal_cannot_rotate_twice(self):
        directory, journal = self.fixture()
        def reopen():
            (directory / 'active.log').write_bytes(b'new')
        rotate(directory, 'active.log', 'retained.log', journal,
               lambda: None, lambda info: True, reopen, lambda old, new: None)
        with self.assertRaises(FileExistsError):
            rotate(directory, 'active.log', 'second.log', journal,
                   lambda: None, lambda info: True, reopen, lambda old, new: None)
        self.assertFalse((directory / 'second.log').exists())

    def test_health_failure_after_rename_does_not_signal_broker(self):
        directory, journal = self.fixture()
        calls = []
        def guard():
            if (directory / 'retained.log').exists():
                raise RotationStopped('dns_failed')
        with self.assertRaisesRegex(RotationStopped, 'dns_failed'):
            rotate(directory, 'active.log', 'retained.log', journal,
                   guard, lambda info: True, lambda: calls.append('signal'),
                   lambda old, new: None)
        self.assertEqual(calls, [])
        self.assertTrue((directory / 'active.log').exists())

    def test_hard_links_and_traversal_are_rejected(self):
        import os
        directory, journal = self.fixture()
        os.link(directory / 'active.log', directory / 'alias.log')
        with self.assertRaises(RotationStopped):
            rotate(directory, 'active.log', 'retained.log', journal,
                   lambda: None, lambda info: True, lambda: None, lambda old, new: None)
        with self.assertRaises(RotationStopped):
            rotate(directory, 'active.log', '../retained.log', journal,
                   lambda: None, lambda info: True, lambda: None, lambda old, new: None)
