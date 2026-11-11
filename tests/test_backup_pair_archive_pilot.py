import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from governor.backup_pair_archive_pilot import PilotStopped, build_archive, encrypted_readback, restore_files, select_pair


class BackupPairPilotTests(unittest.TestCase):
    def fixture(self, base):
        names = ("private-a-20260501-120000", "private-b-20260501-120000")
        files = (b"synthetic configuration", b"synthetic state")
        for name, content in zip(names, files):
            group = base / name
            group.mkdir()
            (group / "file").write_bytes(content)
        groups = {name: {"files": 1, "bytes": len(content)}
                  for name, content in zip(names, files)}
        return select_pair(groups, ["private-a", "private-b"]), files

    def test_restores_both_files_and_preserves_unverified_relationship(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (stamp, selected), files = self.fixture(root)
            output = io.BytesIO()
            manifest, count, size = build_archive(root, stamp, selected, output)
            self.assertEqual((count, size), (2, sum(map(len, files))))
            self.assertIsNone(manifest["superseded_by"])
            self.assertEqual(manifest["runtime_dependencies"], "unverified")
            target = root / "isolated"
            target.mkdir()
            restore_files(output, manifest, target)
            self.assertEqual([(target / f"group-{n}" / "file").read_bytes()
                              for n in (1, 2)], list(files))

    def test_rejects_symlink_instead_of_reading_outside_selected_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (stamp, selected), _ = self.fixture(root)
            (root / selected[0][0] / "private-link").symlink_to(root / selected[1][0] / "file")
            with self.assertRaises(PilotStopped):
                build_archive(root, stamp, selected, io.BytesIO())

    @unittest.skipUnless(shutil.which("restic"), "requires Restic")
    def test_encrypted_repository_readback_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (stamp, selected), _ = self.fixture(root)
            env = {**os.environ, "RESTIC_REPOSITORY": str(root / "repo"),
                   "RESTIC_PASSWORD": "synthetic-fixture-password"}
            subprocess.run(["restic", "--no-cache", "init"], env=env, check=True,
                           stdout=subprocess.DEVNULL, timeout=30)
            with tempfile.TemporaryFile() as archive:
                manifest, _, _ = build_archive(root, stamp, selected, archive)
                encrypted_readback(archive, env, manifest)
                archive.seek(0)
                encrypted_readback(archive, env, manifest)
            self.assertTrue((root / selected[0][0] / "file").is_file())
