import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from governor.adguard_archive_restic_proof import backup_archive


@unittest.skipUnless(Path("/usr/bin/restic").exists(), "system Restic required")
class EncryptedArchiveTests(unittest.TestCase):
    def test_writes_and_reads_back_only_eligible_archive_and_reuses_verified_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = dict(os.environ, RESTIC_REPOSITORY=str(root / "repo"),
                       RESTIC_PASSWORD="synthetic-ci-only", HOME=str(root))
            subprocess.run(["/usr/bin/restic", "--no-cache", "init"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30, check=True)
            source = root / "backup.tar.gz"
            fixtures = {"opt/stacks/adguard/conf/AdGuardHome.yaml": b"schema_version: 29\n"}
            for expected in ("archive_recovery_coverage_unverified", "encrypted_archive_verified"):
                with tarfile.open(source, "w:gz") as archive:
                    for name, content in fixtures.items():
                        item = tarfile.TarInfo(name)
                        item.size = len(content)
                        archive.addfile(item, io.BytesIO(content))
                self.assertEqual(backup_archive(source, env), expected)
                fixtures["opt/stacks/adguard/work/data/stats.db"] = b"synthetic-work"
            self.assertEqual(backup_archive(source, env), "encrypted_archive_already_verified")
