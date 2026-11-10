import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from governor.adguard_restic_tree_probe import recover_tree


@unittest.skipUnless(Path("/usr/bin/restic").exists(), "system Restic required")
class TreeRecoveryTests(unittest.TestCase):
    def test_encrypted_snapshot_recovers_config_and_work_but_not_config_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tree = root / "adguard"
            env = dict(os.environ, RESTIC_REPOSITORY=str(root / "repo"),
                       RESTIC_PASSWORD="synthetic-ci-only", HOME=str(root))

            def restic(*args):
                subprocess.run(["/usr/bin/restic", "--no-cache", *args], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=30, check=True)

            restic("init")
            (tree / "conf").mkdir(parents=True)
            (tree / "conf/AdGuardHome.yaml").write_text("schema_version: 29\n")
            restic("backup", "--tag", "lifeos-pi5", "--time", "2026-01-01 00:00:00", str(tree))
            self.assertEqual(recover_tree(env, str(tree), 1024**2)["status"],
                             "expected_work_data_missing")
            (tree / "work/data").mkdir(parents=True)
            payload = b"synthetic-work"
            (tree / "work/data/stats.db").write_bytes(payload)
            restic("backup", "--tag", "lifeos-pi5", "--time", "2026-01-02 00:00:00", str(tree))
            shutil.rmtree(tree)
            self.assertEqual(recover_tree(env, str(tree), 1024**2), {
                "status": "adguard_config_and_work_recovered", "scope": "adguard_tree",
                "work_files": 1, "work_bytes": len(payload),
            })
