import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import sqlite3
from unittest.mock import patch

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
    def test_chroma_preserves_extra_disk_segment_and_requires_all_metadata_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with sqlite3.connect(root / 'paperless_iq.db') as db:
                db.execute('CREATE TABLE fixture (id INTEGER)')
            chroma = root / 'chroma'
            chroma.mkdir()
            with sqlite3.connect(chroma / 'chroma.sqlite3') as db:
                db.execute('CREATE TABLE segments (id TEXT, scope TEXT)')
                db.execute("INSERT INTO segments VALUES ('required', 'VECTOR')")
            for segment in ('required', 'extra'):
                path = chroma / segment
                path.mkdir()
                for name in ('header.bin', 'data_level0.bin', 'length.bin', 'link_lists.bin'):
                    (path / name).write_bytes(b'x')
            evidence = {}
            rehearsal.iq_verify(root, lambda: None, evidence)
            self.assertEqual(evidence['chroma_disk_segments_unmapped'], 1)
            self.assertEqual(evidence['chroma_vector_rows_without_disk'], 0)
            self.assertTrue((chroma / 'extra/header.bin').exists())
            (chroma / 'required/header.bin').unlink()
            with self.assertRaises(rehearsal.RehearsalError):
                rehearsal.iq_verify(root, lambda: None)

    def test_native_chroma_uses_isolated_image_and_staged_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'chroma.sqlite3').touch()
            image = 'sha256:' + 'a' * 64
            evidence = {}
            with patch.object(rehearsal, 'command', side_effect=[image, 'CHROMA_NATIVE_RESULT=[2,200,2]', '', '']) as run:
                rehearsal.chroma_native_proof(root, 'random-test', lambda: None, evidence)
            args = run.call_args_list[1].args[0]
            self.assertIn('--network=none', args)
            self.assertIn('--read-only', args)
            self.assertIn(f'type=bind,src={root},dst=/recovery', args)
            self.assertNotIn('-p', args)
            self.assertEqual(evidence['chroma_native_restore'], 'PASS')
            self.assertEqual(evidence['iq_temporary_cleanup'], 'PASS')

    def test_failure_categories_suppress_private_exception_text(self):
        self.assertEqual(rehearsal.failure_code(OSError('private path')), 'LOCAL_OS_ERROR')
        self.assertEqual(rehearsal.failure_code(ValueError('PRIVATE_RECORD')), 'LOCAL_OPERATION_FAILED')
        self.assertEqual(rehearsal.failure_code(rehearsal.RehearsalError('POSTGRES_START')), 'POSTGRES_START')

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
