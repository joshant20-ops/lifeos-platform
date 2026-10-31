"""Isolated DNS/TLS/proxy transaction proofs; no live host or network access."""
import base64
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('configure_audiobooks_access_test', REPO / 'services/audiobookshelf/configure_access.py')
ACCESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACCESS)
REAL_EXISTING_ROUTES = ACCESS.existing_routes
REAL_VERIFY = ACCESS.verify
BASELINE = {'existing': ('original-start', 'healthy')}
ADDRESS = '192.0.2.1'  # RFC 5737 synthetic documentation address, never a live host.


class ConfigureAccessTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'private/audiobookshelf/access'
        self.state.mkdir(parents=True, mode=0o700)
        os.chmod(self.state.parent, 0o700)
        self.npm = self.root / 'npm/data'
        self.custom = self.npm / 'nginx/custom'
        self.custom.mkdir(parents=True)
        self.certs = self.npm / 'custom_ssl/lifeos-audiobooks'
        self.certs.mkdir(parents=True)
        (self.npm / 'nginx/proxy_host').mkdir()
        self.route = self.custom / 'lifeos-audiobooks.conf'
        self.include = self.custom / 'http.conf'
        self.ca = self.state / 'local-ca.crt'
        self.ca_key = self.state / 'local-ca.key'
        self.ca.write_text('public-ca-cert\n')
        self.ca_key.write_text('never-print-private-ca-key\n')
        os.chmod(self.ca_key, 0o600)
        self.calls = []
        self.api_calls = []
        self.output = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)
        for name, value in [('STATE', self.state), ('NPM', self.npm), ('CUSTOM', self.custom), ('ROUTE', self.route), ('INCLUDE', self.include), ('CERTS', self.certs)]:
            self.stack.enter_context(patch.object(ACCESS, name, value))
        self.stack.enter_context(patch.object(ACCESS.os, 'geteuid', return_value=0))
        self.stack.enter_context(patch.object(ACCESS.sys, 'argv', ['configure_access.py']))
        # Model installed root ownership on unprivileged hosted CI workers too.
        real_stat = os.stat
        def trusted_stat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if str(path).startswith(str(self.root)):
                fields = list(result)
                fields[4] = 0
                fields[5] = 0
                return os.stat_result(fields)
            return result
        self.stack.enter_context(patch.object(ACCESS.os, 'stat', side_effect=trusted_stat))
        self.chown = self.stack.enter_context(patch.object(ACCESS.os, 'chown', return_value=None))
        self.native = types.SimpleNamespace(snapshot=lambda: BASELINE.copy())
        self.audit = types.SimpleNamespace(adguard_base=lambda: 'http://127.0.0.1:3001', has_server_name=lambda text, host: host in text)
        self.dns = types.SimpleNamespace(pi_ipv4=lambda: ADDRESS, adguard_ipv4_answers=lambda host, server: ([ADDRESS], None))
        helpers = {'access_audit': self.audit, 'dns_helper': self.dns, 'install_helpers': self.native}
        self.stack.enter_context(patch.object(ACCESS, 'module', side_effect=lambda name, path: helpers[name]))
        self.stack.enter_context(patch.object(ACCESS, 'existing_routes', return_value={'ha.lan': '200', 'vaultwarden.lan': '200'}))
        self.stack.enter_context(patch.object(ACCESS, 'cert_pair', return_value=(self.ca, self.ca_key, False)))
        self.stack.enter_context(patch.object(ACCESS, 'api', side_effect=self.api))
        self.stack.enter_context(patch.object(ACCESS, 'run', side_effect=self.command))
        self.stack.enter_context(patch.object(ACCESS, 'verify', return_value=None))
        self.stack.enter_context(contextlib.redirect_stdout(self.output))

    def api(self, base, path, value=None):
        self.api_calls.append((path, value))
        if path.endswith('/list'):
            return []
        return None

    def command(self, *args):
        self.calls.append(args)
        if args[0] == '/usr/bin/openssl':
            if '-keyout' in args:
                Path(args[args.index('-keyout') + 1]).write_text('never-print-leaf-private-key\n')
            if '-out' in args:
                Path(args[args.index('-out') + 1]).write_text('generated-public-cert-or-csr\n')
            if '-fingerprint' in args:
                return 'sha256 Fingerprint=PUBLIC:TEST:FINGERPRINT'
            if '-outform' in args and args[args.index('-outform') + 1] == 'PEM':
                return '-----BEGIN CERTIFICATE-----\nPUBLIC_TEST_CERTIFICATE\n-----END CERTIFICATE-----'
        return ''

    def test_success_configures_fixed_private_route_and_dns_without_secret_output(self):
        ACCESS.main()
        route = self.route.read_text()
        self.assertIn('server_name audiobooks.lan;', route)
        self.assertIn('deny all;', route)
        self.assertIn('proxy_pass http://lifeos-audiobooks:80;', route)
        self.assertIn('AUDIOBOOKS_ACCESS=PASS', self.output.getvalue())
        self.assertIn((' /control/rewrite/add'.strip(), {'domain': 'audiobooks.lan', 'answer': ADDRESS}), self.api_calls)
        self.assertEqual(stat.S_IMODE((self.certs / 'privkey.pem').stat().st_mode), 0o600)
        self.assertNotIn('never-print-', self.output.getvalue())
        self.assertNotIn(ADDRESS, self.output.getvalue())
        self.assertEqual(self.include.read_text().count(ACCESS.INCLUDE_LINE), 1)

    def test_conflicting_dns_rewrite_refused_before_config_mutation(self):
        with patch.object(ACCESS, 'api', return_value=[{'domain': 'audiobooks.lan', 'answer': 'different-answer'}]):
            with self.assertRaises(ValueError):
                ACCESS.main()
        self.assertFalse(self.route.exists())
        self.assertFalse((self.certs / 'privkey.pem').exists())

    def test_root_and_no_arguments_required(self):
        with patch.object(ACCESS.os, 'geteuid', return_value=1000):
            with self.assertRaises(ValueError):
                ACCESS.main()
        with patch.object(ACCESS.sys, 'argv', ['configure_access.py', 'arbitrary']):
            with self.assertRaises(ValueError):
                ACCESS.main()
        self.assertEqual(self.api_calls, [])

    def test_preexisting_unmanaged_route_refused(self):
        (self.npm / 'nginx/proxy_host/1.conf').write_text('server_name audiobooks.lan;')
        with self.assertRaises(ValueError):
            ACCESS.main()
        self.assertFalse(self.route.exists())

    def test_initial_failure_removes_route_include_and_only_new_dns(self):
        with patch.object(ACCESS, 'verify', side_effect=ValueError('test failure')), patch.object(ACCESS.time, 'sleep'):
            with self.assertRaises(ValueError):
                ACCESS.main()
        self.assertFalse(self.route.exists())
        self.assertFalse(self.include.exists())
        self.assertTrue(any(path.endswith('/delete') for path, _ in self.api_calls))
        self.assertIn('AUDIOBOOKS_ACCESS_ROLLBACK=PASS', self.output.getvalue())

    def test_existing_exact_rewrite_is_never_deleted_on_proxy_failure(self):
        def exact_api(base, path, value=None):
            self.api_calls.append((path, value))
            return [{'domain': 'audiobooks.lan', 'answer': ADDRESS}] if path.endswith('/list') else None
        with patch.object(ACCESS, 'api', side_effect=exact_api), patch.object(ACCESS, 'verify', side_effect=ValueError('test failure')), patch.object(ACCESS.time, 'sleep'):
            with self.assertRaises(ValueError):
                ACCESS.main()
        self.assertFalse(any(path.endswith('/add') or path.endswith('/delete') for path, _ in self.api_calls))

    def test_repeated_failure_restores_previous_tls_files_and_include(self):
        self.route.write_text(ACCESS.render())
        self.include.write_text('# existing custom config\n' + ACCESS.INCLUDE_LINE)
        originals = {'privkey.pem': 'previous-private-key', 'fullchain.pem': 'previous-leaf-chain', 'ca.crt': 'previous-public-ca'}
        for name, text in originals.items():
            (self.certs / name).write_text(text)
            os.chmod(self.certs / name, 0o600 if name == 'privkey.pem' else 0o644)
        with patch.object(ACCESS, 'verify', side_effect=ValueError('test failure')), patch.object(ACCESS.time, 'sleep'):
            with self.assertRaises(ValueError):
                ACCESS.main()
        for name, text in originals.items():
            self.assertEqual((self.certs / name).read_text(), text)
        self.assertEqual(self.include.read_text(), '# existing custom config\n' + ACCESS.INCLUDE_LINE)
        self.assertEqual(self.route.read_text(), ACCESS.render())

    def test_existing_leaf_and_private_key_symlinks_are_refused(self):
        target = self.root / 'unrelated-secret'
        target.write_text('unrelated-private-data')
        for name in ('server.crt', 'server.key'):
            with self.subTest(name=name):
                leaf = self.state / 'server.crt'
                key = self.state / 'server.key'
                leaf.unlink(missing_ok=True); key.unlink(missing_ok=True)
                leaf.write_text('existing-public-leaf'); key.write_text('existing-private-key')
                path = self.state / name
                path.unlink(); path.symlink_to(target)
                with self.assertRaises(ValueError):
                    ACCESS.main()
                self.assertEqual(target.read_text(), 'unrelated-private-data')

    def test_world_writable_private_state_is_refused(self):
        os.chmod(self.state, 0o777)
        with self.assertRaises(ValueError):
            ACCESS.main()
        self.assertFalse(self.route.exists())

    def test_failed_nginx_rollback_still_attempts_dns_rollback(self):
        reload_count = 0
        original = self.command
        def fail_rollback(*args):
            nonlocal reload_count
            if args[-2:] == ('-s', 'reload'):
                reload_count += 1
                if reload_count > 1:
                    raise subprocess.CalledProcessError(1, args)
            return original(*args)
        with patch.object(ACCESS, 'run', side_effect=fail_rollback), patch.object(ACCESS, 'verify', side_effect=ValueError('test failure')), patch.object(ACCESS.time, 'sleep'):
            with self.assertRaises(Exception):
                ACCESS.main()
        self.assertTrue(any(path.endswith('/delete') for path, _ in self.api_calls))
        self.assertIn('AUDIOBOOKS_ACCESS_ROLLBACK=FAIL', self.output.getvalue())

    def test_write_failure_removes_own_temporary_file(self):
        path = self.root / 'new-config.conf'
        with patch.object(ACCESS.os, 'fsync', side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError):
                ACCESS.write(path, 'new config')
        self.assertFalse(path.exists())
        self.assertFalse(path.with_name(path.name + '.lifeos-new').exists())

    def test_existing_private_include_mode_is_preserved_on_success_and_rollback(self):
        self.include.write_text('# unrelated private custom configuration\n')
        os.chmod(self.include, 0o600)
        ACCESS.main()
        self.assertEqual(stat.S_IMODE(self.include.stat().st_mode), 0o600)
        self.assertTrue(any(call.args[1:] == (0, 0) for call in self.chown.call_args_list))
        def exact_api(base, path, value=None):
            return [{'domain': 'audiobooks.lan', 'answer': ADDRESS}] if path.endswith('/list') else None
        before = self.include.read_text()
        with patch.object(ACCESS, 'api', side_effect=exact_api), patch.object(ACCESS, 'verify', side_effect=ValueError('test failure')), patch.object(ACCESS.time, 'sleep'):
            with self.assertRaises(ValueError):
                ACCESS.main()
        self.assertEqual(self.include.read_text(), before)
        self.assertEqual(stat.S_IMODE(self.include.stat().st_mode), 0o600)

    def test_repeat_success_uses_existing_exact_material_without_readding_dns(self):
        ACCESS.main()
        before = {p.name: (p.read_text(), p.stat().st_mtime_ns) for p in self.certs.iterdir()}
        self.api_calls.clear()
        def exact_api(base, path, value=None):
            self.api_calls.append((path, value))
            return [{'domain': 'audiobooks.lan', 'answer': ADDRESS}] if path.endswith('/list') else None
        with patch.object(ACCESS, 'api', side_effect=exact_api):
            ACCESS.main()
        self.assertEqual({p.name: (p.read_text(), p.stat().st_mtime_ns) for p in self.certs.iterdir()}, before)
        self.assertFalse(any(path.endswith('/add') or path.endswith('/delete') for path, _ in self.api_calls))
        self.assertEqual(self.include.read_text().count(ACCESS.INCLUDE_LINE), 1)

    def test_baseline_regression_rolls_back_without_claiming_success(self):
        self.native.snapshot = iter([BASELINE.copy(), {}]).__next__
        with self.assertRaises(ValueError):
            ACCESS.main()
        self.assertFalse(self.route.exists())
        self.assertIn('AUDIOBOOKS_ACCESS_ROLLBACK=PASS', self.output.getvalue())
        self.assertNotIn('AUDIOBOOKS_ACCESS=PASS', self.output.getvalue())
        self.assertTrue(any(path.endswith('/delete') for path, _ in self.api_calls))

    def test_write_never_removes_preexisting_unowned_temp(self):
        path = self.root / 'new-config.conf'
        temporary = path.with_name(path.name + '.lifeos-new')
        temporary.write_text('preexisting content')
        with self.assertRaises(FileExistsError):
            ACCESS.write(path, 'new config')
        self.assertEqual(temporary.read_text(), 'preexisting content')
        self.assertFalse(path.exists())

    def test_only_generic_public_certificate_is_exported(self):
        self.ca.write_text('public-ca-cert\nnever-export-trailing-private-material\n')
        ACCESS.main()
        output = self.output.getvalue()
        encoded = next(line.split('=', 1)[1] for line in output.splitlines() if line.startswith('AUDIOBOOKS_PUBLIC_CA_PEM_B64='))
        certificate = base64.b64decode(encoded).decode()
        self.assertEqual(certificate, '-----BEGIN CERTIFICATE-----\nPUBLIC_TEST_CERTIFICATE\n-----END CERTIFICATE-----\n')
        self.assertNotIn('private-material', certificate)
        self.assertNotIn('private-ca-key', certificate)

    def test_existing_user_ca_certificate_is_not_exported(self):
        with patch.object(ACCESS, 'cert_pair', return_value=(self.ca, self.ca_key, True)):
            ACCESS.main()
        self.assertNotIn('AUDIOBOOKS_PUBLIC_CA_PEM_B64=', self.output.getvalue())
        self.assertIn('EXISTING_LOCAL_CA_REUSED=YES', self.output.getvalue())

    def test_existing_route_helper_uses_private_lan_resolve_target(self):
        with patch.object(ACCESS, 'run', side_effect=['200', '200']) as command:
            self.assertEqual(REAL_EXISTING_ROUTES(ADDRESS), {'ha.lan': '200', 'vaultwarden.lan': '200'})
        self.assertEqual(len(command.call_args_list), 2)
        for call, name, port in zip(command.call_args_list, ('ha.lan', 'vaultwarden.lan'), (80, 443)):
            args = call.args
            self.assertEqual(args[args.index('--resolve') + 1], name + ':' + str(port) + ':' + ADDRESS)
            self.assertEqual(args[args.index('-o') + 1], '/dev/null')
            self.assertEqual(args[args.index('--max-time') + 1], '10')

    def test_new_audiobook_verifier_keeps_strict_loopback_tls(self):
        with patch.object(ACCESS, 'run', side_effect=[json.dumps({'app': 'audiobookshelf', 'isInit': True}), '401']) as command:
            REAL_VERIFY(self.ca)
        self.assertEqual(len(command.call_args_list), 2)
        for call in command.call_args_list:
            args = call.args
            self.assertEqual(args[args.index('--resolve') + 1], 'audiobooks.lan:443:127.0.0.1')
            self.assertEqual(args[args.index('--cacert') + 1], str(self.ca))
            self.assertNotIn('-k', args)

    def test_gateway_rejects_arbitrary_configure_arguments(self):
        loader = importlib.machinery.SourceFileLoader('configure_access_gateway_test', str(REPO / 'homelab/live/usr/local/sbin/lifeos-deploy-gateway'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        gateway = importlib.util.module_from_spec(spec)
        loader.exec_module(gateway)
        self.assertEqual(gateway.parse_request(['configure-audiobooks-access']), ('configure-audiobooks-access', []))
        with self.assertRaises(SystemExit) as error:
            gateway.parse_request(['configure-audiobooks-access', '/tmp/other'])
        self.assertEqual(error.exception.code, 64)
        wrapper = (REPO / 'scripts/lifeos-configure-audiobooks-access.sh').read_text()
        self.assertIn('/usr/bin/env -i', wrapper)
        self.assertIn('/usr/bin/python3 -I', wrapper)


if __name__ == '__main__':
    unittest.main()
