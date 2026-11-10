import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from governor.adguard_restic_probe import recover_config


@unittest.skipUnless(shutil.which("restic") and Path("/usr/bin/restic").exists(),
                     "system Restic required for encrypted repository integration proof")
class ResticProbeTests(unittest.TestCase):
    def test_recovers_tagged_configuration_and_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            config = root / "AdGuardHome.yaml"
            config.write_text("schema_version: 29\n", encoding="utf-8")
            env = dict(os.environ, RESTIC_REPOSITORY=str(repo),
                       RESTIC_PASSWORD="synthetic-ci-only", HOME=str(root))
            for args in (["init"], ["backup", "--tag", "lifeos-pi5", str(config)]):
                subprocess.run(["/usr/bin/restic", "--no-cache", *args], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=30, check=True)
            config.unlink()
            self.assertTrue(recover_config(env, str(config)))
            self.assertFalse(recover_config(env, str(root / "missing.yaml")))
