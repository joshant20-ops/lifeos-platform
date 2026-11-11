from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from governor.mqtt_retained_log_archive import ArchiveUnverified, preserve


class RetainedLogArchiveTests(unittest.TestCase):
    def test_unverified_writer_blocks_before_restic_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "retained.log"
            log.write_bytes(b"synthetic")
            with self.assertRaisesRegex(ArchiveUnverified, "changed_or_open"):
                preserve(log, {}, lambda _: False)

    @unittest.skipUnless(shutil.which("restic"), "requires Restic")
    def test_encrypted_streaming_readback_and_retry_preserve_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {**os.environ, "RESTIC_REPOSITORY": str(root / "repository"),
                   "RESTIC_PASSWORD": "synthetic-fixture-password"}
            subprocess.run(["restic", "--no-cache", "init"], env=env, check=True,
                           stdout=subprocess.DEVNULL, timeout=30)
            log = root / "retained.log"
            data = b"synthetic MQTT payload\n" * 65536
            log.write_bytes(data)
            first = preserve(log, env, lambda _: True, timeout=30)
            self.assertEqual(first["verified_bytes"], len(data))
            self.assertEqual(first["reclaimed_bytes"], 0)
            self.assertEqual(preserve(log, env, lambda _: True, timeout=30), first)
            self.assertEqual(log.read_bytes(), data)
