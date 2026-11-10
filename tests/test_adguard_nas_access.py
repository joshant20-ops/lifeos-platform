from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from governor import adguard_nas_access as probe


class NasAccessTests(unittest.TestCase):
    def test_opened_mount_must_be_nfs_layer(self):
        mounts = (
            "31 1 0:2 / /mnt/synology-backups rw - autofs systemd-1 rw\n"
            "32 31 0:3 / /mnt/synology-backups rw - nfs4 example:/backups rw\n"
        )
        self.assertTrue(probe.mount_matches(probe.SHARE, "32", mounts))
        self.assertFalse(probe.mount_matches(probe.SHARE, "31", mounts))

    def test_non_nas_is_refused_before_creating_any_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertEqual(probe.check_access(path), {"status": "nas_mount_not_verified"})
            self.assertEqual(list(path.iterdir()), [])

    def test_reports_mode_and_ownership_without_exposing_uid(self):
        info = SimpleNamespace(st_mode=0o750, st_uid=1000)
        self.assertEqual(probe.private_stage_status(info, 1001), {
            "status": "nas_private_directory_check_failed", "mode": "0750",
            "owner_matches_runner": False,
        })
        info.st_mode = 0o700
        self.assertEqual(probe.private_stage_status(info, 1000)["status"],
                         "nas_private_directory_verified")
