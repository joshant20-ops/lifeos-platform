import importlib.util
import contextlib
import io
import pathlib
import runpy
import stat
import unittest
from unittest.mock import MagicMock, Mock, patch

spec = importlib.util.spec_from_file_location('audit', pathlib.Path(__file__).parents[1] / 'governor/paperless_capability_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class CapabilityAuditTests(unittest.TestCase):
    def test_non_nfs_targets_are_never_read(self):
        with contextlib.redirect_stdout(io.StringIO()):
            inventory = runpy.run_path(str(pathlib.Path(audit.__file__).with_name('paperless_native_inventory.py')))
        mounts = '1 2 0:1 / /usr/src/paperless/consume rw - ext4 /dev/none rw\n'
        with patch('builtins.open', return_value=io.StringIO(mounts)), patch('os.scandir') as scan, patch.object(pathlib.Path, 'lstat') as lstat:
            self.assertEqual(inventory['nas_inventory'](), {'EXPORT_NFS': 'FALSE', 'INTAKE_NFS': 'FALSE'})
        scan.assert_not_called()
        lstat.assert_not_called()

    def test_nfs_inventory_rejects_unsafe_manifests_and_caps_entries(self):
        with contextlib.redirect_stdout(io.StringIO()):
            inventory = runpy.run_path(str(pathlib.Path(audit.__file__).with_name('paperless_native_inventory.py')))
        mounts = ''.join(f'1 2 0:1 / /usr/src/paperless/{target} rw - nfs4 hidden rw\n' for target in ('consume', 'export'))
        entry = Mock()
        entry.is_file.return_value = True
        entry.is_dir.return_value = False
        scanned = MagicMock()
        for info in (Mock(st_mode=stat.S_IFLNK, st_mtime=120, st_size=1), Mock(st_mode=stat.S_IFREG, st_mtime=500, st_size=1)):
            scanned.__enter__.return_value = iter([entry] * 501)
            with patch('builtins.open', return_value=io.StringIO(mounts)), patch('os.scandir', return_value=scanned), patch.object(pathlib.Path, 'lstat', return_value=info), patch('time.time', return_value=300):
                out = inventory['nas_inventory']()
            self.assertEqual(out['INTAKE_ROOT_FILES'], 500)
            self.assertEqual(out['INTAKE_ROOT_COUNT_CAPPED'], 'TRUE')
            self.assertNotIn('EXPORT_MANIFEST_AGE_HOURS', out)
        entry.is_file.assert_called_with(follow_symlinks=False)
        entry.is_dir.assert_called_with(follow_symlinks=False)

    def test_native_stdout_cannot_leak_values_or_inject_markers(self):
        import json
        self.assertEqual(audit.native_result('PRIVATE'), {'RESULT': 'OUTPUT_REJECTED'})
        data = {'DOCUMENTS': 942, 'VERSION': '3.1.2', 'RESULT': 'READ_ONLY_COMPLETE'}
        output = audit.native_result('private banner\nPAPERLESS_NATIVE_JSON=' + json.dumps(data))
        self.assertEqual(output['DOCUMENTS'], 942)
        self.assertNotIn('private', repr(output))
        data['secret'] = 'PRIVATE'
        self.assertEqual(audit.native_result('PAPERLESS_NATIVE_JSON=' + json.dumps(data)), {'RESULT': 'OUTPUT_REJECTED'})
        self.assertEqual(audit.native_result('x' * 32769), {'RESULT': 'OUTPUT_REJECTED'})

    def test_native_wrong_types_are_unknown(self):
        import json
        output = audit.native_result('PAPERLESS_NATIVE_JSON=' + json.dumps({'DOCUMENTS': True, 'VERSION': 'private\nX=PASS', 'RESULT': 'PRIVATE'}))
        self.assertEqual(output['DOCUMENTS'], 'UNKNOWN')
        self.assertEqual(output['VERSION'], 'UNKNOWN')
        self.assertEqual(output['RESULT'], 'OUTPUT_REJECTED')

    def test_only_selected_aggregates_leave_host(self):
        seen = []
        def get(path):
            seen.append(path)
            if path == 'statistics/':
                return {**dict.fromkeys(audit.STATS, 12), 'title': 'PRIVATE', 'inbox_tags': [99]}
            if path == 'ui_settings/':
                return {'user': {'username': 'PRIVATE'}, 'settings': {'version': '3.1.2', 'auditlog_enabled': True, 'ai_enabled': False, 'app_title': 'PRIVATE'}}
            return {'count': 3, 'results': [{'name': 'PRIVATE'}]}
        output = audit.collect(get)
        self.assertNotIn('PRIVATE', repr(output))
        self.assertEqual(output['DOCUMENTS_TOTAL'], 12)
        self.assertEqual(output['COMPLETENESS'], 'AVAILABLE')
        self.assertEqual(len(seen), 6)
        self.assertTrue(all(p.endswith('/?page_size=1') for p in seen[1:6]))

    def test_invalid_values_never_become_evidence(self):
        def get(path):
            return {'count': True, 'documents_total': -1, 'settings': {'version': 'PRIVATE\nX=PASS', 'auditlog_enabled': 'true'}}
        output = audit.collect(get)
        self.assertEqual(output['WORKFLOWS_COUNT'], 'UNKNOWN')
        self.assertEqual(output['DOCUMENTS_TOTAL'], 'UNKNOWN')
        self.assertNotIn('PRIVATE', repr(output))
        self.assertEqual(output['COMPLETENESS'], 'PARTIAL')

    def test_unavailable_is_not_zero_or_acceptance(self):
        output = audit.collect(lambda _: None)
        self.assertEqual(output['DOCUMENTS_TOTAL'], 'UNKNOWN')
        self.assertEqual(output['COMPLETENESS'], 'PARTIAL')
        self.assertNotIn('PASS', output.values())

    def test_redirect_refused(self):
        self.assertIsNone(audit.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))


if __name__ == '__main__':
    unittest.main()
