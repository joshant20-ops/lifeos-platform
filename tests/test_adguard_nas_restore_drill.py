import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from governor import adguard_nas_restore_drill as drill


class NasRestoreDrillTests(unittest.TestCase):
    def test_verified_copy_is_the_restore_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, copied = root / "source.tar.gz", root / "copy.tar.gz"
            payload = b"schema_version: 29\n"
            with tarfile.open(source, "w:gz") as archive:
                config = tarfile.TarInfo("conf/AdGuardHome.yaml")
                config.size = len(payload)
                archive.addfile(config, io.BytesIO(payload))
            drill.copy_archive(source, copied)
            source.unlink()
            report = drill.restore_files(copied, root / "restored")
            self.assertEqual(report["status"], "file_restore_verified")
            self.assertEqual((root / "restored/conf/AdGuardHome.yaml").read_bytes(), payload)

    def test_archive_cannot_escape_or_follow_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, member in enumerate((tarfile.TarInfo("../escape"), tarfile.TarInfo("alias"))):
                if index:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "../escape"
                archive_path = root / f"archive-{index}.tar.gz"
                with tarfile.open(archive_path, "w:gz") as archive:
                    archive.addfile(member)
                with self.assertRaises(drill.DrillFailure):
                    drill.restore_files(archive_path, root / f"restored-{index}")
                self.assertFalse((root / "escape").exists())

    def test_mount_id_must_select_nfs_above_automount(self):
        share = Path("/mnt/synology-backups")
        mounts = (
            "1 0 8:1 / / rw - ext4 /dev/example rw\n"
            "31 1 0:2 / /mnt/synology-backups rw - autofs systemd-1 rw\n"
            "32 31 0:3 / /mnt/synology-backups rw - nfs4 example:/backups rw\n"
        )
        self.assertTrue(drill.mount_matches(share, "32", mounts))
        self.assertFalse(drill.mount_matches(share, "31", mounts))
        self.assertFalse(drill.mount_matches(share, "1", mounts))
        self.assertFalse(drill.mount_matches(share, None, mounts))

    def test_privacy_result_reports_mode_without_disclosing_uid(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            path.chmod(0o750)
            self.assertEqual(drill.private_stage_status(path.stat(), os.geteuid()),
                             {"mode": "0750", "owner_matches_runner": True})
