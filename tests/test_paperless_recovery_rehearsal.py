import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from governor import paperless_recovery_rehearsal as rehearsal


def archive(name, kind=tarfile.REGTYPE, data=b"private fixture"):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as output:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.size = len(data) if kind == tarfile.REGTYPE else 0
        output.addfile(member, io.BytesIO(data) if member.size else None)
    buffer.seek(0)
    return buffer


class RecoverySafetyTests(unittest.TestCase):
    def test_historical_format_inventory_does_not_require_eml_or_emit_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('private.EML', 'private.tar', 'private.gz', 'private.bin'):
                (root / name).write_bytes(b'private')
            result = rehearsal.historical_email_inventory(root, lambda: None)
            self.assertEqual(result['historical_eml_files'], 1)
            self.assertEqual(result['historical_tar_files'], 1)
            self.assertEqual(result['historical_gzip_files'], 1)
            self.assertEqual(result['historical_other_files'], 1)
            self.assertNotIn('private', repr(result))
            (root / 'private.EML').unlink()
            self.assertEqual(rehearsal.historical_email_inventory(root, lambda: None)['historical_eml_files'], 0)

    def test_extract_preserves_bytes_under_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            source = archive("./originals/test.pdf")
            count, size = rehearsal.extract(source, target, lambda: None, 100)
            self.assertEqual((count, size), (1, 15))
            self.assertEqual((target / "originals/test.pdf").read_bytes(), b"private fixture")

    def test_extract_rejects_escape_links_and_over_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for source in (archive("../outside"), archive("/outside"), archive("link", tarfile.SYMTYPE), archive("large")):
                with self.assertRaises(ValueError):
                    rehearsal.extract(source, target, lambda: None, 5)
            self.assertEqual(list(target.iterdir()), [])

    def test_manifest_is_a_closed_set_of_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = hashlib.sha256(b"x").hexdigest()
            manifest = root / "SHA256SUMS"
            lines = [f"{digest}  ./{name}" for name in rehearsal.ARCHIVES]
            manifest.write_text("\n".join(lines))
            self.assertEqual(set(rehearsal.read_manifest(root)), set(rehearsal.ARCHIVES))
            manifest.write_text("\n".join([*lines[:-1], lines[0]]))
            with self.assertRaises(ValueError):
                rehearsal.read_manifest(root)
            (root / "link").symlink_to(manifest)
            with self.assertRaises(OSError), rehearsal.regular_source(root, "link"):
                pass


if __name__ == "__main__":
    unittest.main()
