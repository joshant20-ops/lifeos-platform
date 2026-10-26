import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

FLAGS = ["-aHAXx", "--numeric-ids"]
class PreservationContract(unittest.TestCase):
    def test_copy_preserves_links_modes_and_detects_corruption_and_extras(self):
        self.assertIsNotNone(shutil.which("rsync"), "rsync required for preservation proof")
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp)/"source", Path(tmp)/"dest"
            source.mkdir(); dest.mkdir()
            (source/"data").write_bytes(b"recovery evidence")
            (source/"data").chmod(0o640)
            os.link(source/"data", source/"hardlink")
            (source/"symlink").symlink_to("data")
            subprocess.run(["rsync", *FLAGS, str(source)+"/", str(dest)+"/"], check=True, capture_output=True)
            self.assertEqual((dest/"data").stat().st_ino, (dest/"hardlink").stat().st_ino)
            self.assertEqual(os.readlink(dest/"symlink"), "data")
            self.assertEqual((dest/"data").stat().st_mode & 0o777, 0o640)
            def compare():
                return subprocess.run(["rsync", "-aHAXxnc", "--numeric-ids", "--delete", "--dry-run", "--itemize-changes", str(source)+"/", str(dest)+"/"], check=True, capture_output=True).stdout
            self.assertEqual(compare(), b"")
            (dest/"data").write_bytes(b"corrupt")
            self.assertTrue(compare())
            self.assertEqual((source/"data").read_bytes(), b"recovery evidence")
            (dest/"data").write_bytes(b"recovery evidence")
            (dest/"extra").write_bytes(b"unexpected")
            self.assertIn(b"extra", compare())
            self.assertTrue((dest/"extra").exists(), "verification must not delete")

    def test_shell_parses_and_rejects_arguments_before_privilege(self):
        script = Path(__file__).resolve().parents[1]/"scripts/lifeos-storage-preserve-sd-source.sh"
        subprocess.run(["bash", "-n", str(script)], check=True)
        cp = subprocess.run(["bash", str(script), "unexpected"], capture_output=True)
        self.assertEqual(cp.returncode, 64)

if __name__ == "__main__":
    unittest.main()
