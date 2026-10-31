"""Read-only audiobook access checks, isolated from host files and network."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('audiobooks_access_under_test', REPO / 'services/audiobookshelf/access_audit.py')
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
LOADER = importlib.machinery.SourceFileLoader('audiobooks_access_gateway_test', str(REPO / 'homelab/live/usr/local/sbin/lifeos-deploy-gateway'))
GATEWAY_SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
GATEWAY = importlib.util.module_from_spec(GATEWAY_SPEC)
LOADER.exec_module(GATEWAY)


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return json.dumps(self.payload).encode()[:size]


class AccessAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.npm = self.root / 'npm'
        self.configs = self.npm / 'data/nginx/proxy_host'
        self.configs.mkdir(parents=True)
        self.adguard = self.root / 'AdGuardHome.yaml'
        self.adguard.write_text('http:\n  address: 0.0.0.0:3001\nusers:\n  - password: never-print-this-test-secret\n')
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(AUDIT, 'NPM', self.npm))
        self.stack.enter_context(patch.object(AUDIT, 'ADGUARD', self.adguard))
        self.stack.enter_context(patch.object(AUDIT.os, 'geteuid', return_value=0))
        self.stack.enter_context(patch.object(AUDIT.sys, 'argv', ['access_audit.py']))

    def cert(self, category='data/custom_ssl'):
        path = self.npm / category / 'npm-1/fullchain.pem'
        path.parent.mkdir(parents=True)
        path.write_text('public certificate placeholder')
        return path

    def execute(self, rewrite_rows=None):
        output = io.StringIO()
        result = json.dumps({'app': 'audiobookshelf', 'isInit': True})
        with patch.object(AUDIT, 'certificates', return_value=[]), patch.object(AUDIT.OPENER, 'open', return_value=Response(rewrite_rows or [])) as http, patch.object(AUDIT, 'command', return_value=result) as command, contextlib.redirect_stdout(output):
            AUDIT.main()
        return output.getvalue(), http, command

    def test_certificate_hostname_mismatch_is_not_ready_despite_exit_zero(self):
        self.cert()
        with patch.object(AUDIT, 'command', return_value='Hostname audiobooks.lan does NOT match certificate') as command:
            self.assertEqual(AUDIT.certificates(), [])
        self.assertEqual(command.call_count, 1)

    def test_certificate_match_and_validity_are_both_required(self):
        cert = self.cert()
        with patch.object(AUDIT, 'command', side_effect=['Hostname audiobooks.lan does match certificate', 'Certificate will not expire']) as command:
            self.assertEqual(AUDIT.certificates(), [cert])
        self.assertIn('-checkhost', command.call_args_list[0].args)
        self.assertEqual(command.call_args_list[1].args[-2:], ('-checkend', '86400'))
        self.assertNotIn('privkey', str(command.call_args_list))

    def test_expiring_certificate_is_rejected(self):
        self.cert('letsencrypt/live')
        failure = subprocess.CalledProcessError(1, ['openssl'])
        with patch.object(AUDIT, 'command', side_effect=['Hostname audiobooks.lan does match certificate', failure]):
            self.assertEqual(AUDIT.certificates(), [])

    def test_adguard_loopback_port_without_private_config_output(self):
        self.assertEqual(AUDIT.adguard_base(), 'http://127.0.0.1:3001')
        output, http, command = self.execute([{'domain': 'audiobooks.lan', 'answer': 'private-address-sentinel'}])
        self.assertIn('ADGUARD_REWRITE_API=READY', output)
        self.assertIn('ADGUARD_AUDIOBOOKS_REWRITE=PRESENT', output)
        self.assertIn('NPM_AUDIOBOOKS_UPSTREAM=READY', output)
        self.assertIn('AUDIT_MUTATIONS=NONE', output)
        self.assertNotIn('private-address-sentinel', output)
        self.assertNotIn('never-print-this-test-secret', output)
        self.assertEqual(http.call_args.args[0], 'http://127.0.0.1:3001/control/rewrite/list')
        self.assertIn('http://lifeos-audiobooks/status', command.call_args.args)

    def test_adguard_missing_or_invalid_port_is_refused(self):
        for text in ('http:\n  address: bad\n', 'http:\n  address: 0.0.0.0:65536\n'):
            with self.subTest(text=text):
                self.adguard.write_text(text)
                with self.assertRaises(ValueError):
                    AUDIT.adguard_base()

    def test_exact_existing_routes_reported_without_config_contents(self):
        (self.configs / '1.conf').write_text('server {\n server_name ha.lan vaultwarden.lan;\n ssl_certificate /data/custom_ssl/npm-1/fullchain.pem;\n # never-print-route-secret\n}\n')
        output, _, _ = self.execute()
        self.assertIn('NPM_HA_ROUTE=PRESENT', output)
        self.assertIn('NPM_VAULTWARDEN_ROUTE=PRESENT', output)
        self.assertIn('NPM_VAULTWARDEN_TLS=YES', output)
        self.assertNotIn('never-print-route-secret', output)
        self.assertNotIn('/data/custom_ssl/', output)

    def test_suffix_subdomain_and_commented_names_are_not_existing_routes(self):
        for line in ('server_name evil.vaultwarden.lan vaultwarden.lan.evil;', '# server_name vaultwarden.lan;', 'server_name ha.lan.evil; # vaultwarden.lan'):
            with self.subTest(line=line):
                (self.configs / '1.conf').write_text(line)
                output, _, _ = self.execute()
                self.assertIn('NPM_VAULTWARDEN_ROUTE=ABSENT', output)
                self.assertIn('NPM_HA_ROUTE=ABSENT', output)

    def test_root_and_no_arguments_required_before_discovery(self):
        with patch.object(AUDIT.os, 'geteuid', return_value=1000):
            with self.assertRaises(ValueError):
                AUDIT.main()
        with patch.object(AUDIT.sys, 'argv', ['access_audit.py', 'arbitrary']):
            with self.assertRaises(ValueError):
                AUDIT.main()

    def test_fixed_gateway_operation_and_arbitrary_argument_denial(self):
        self.assertEqual(GATEWAY.OPS['audit-audiobooks-access'], {'script': 'scripts/lifeos-audit-audiobooks-access.sh', 'privileged': True})
        self.assertEqual(GATEWAY.parse_request(['audit-audiobooks-access']), ('audit-audiobooks-access', []))
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            GATEWAY.parse_request(['audit-audiobooks-access', '/tmp/arbitrary'])
        self.assertEqual(error.exception.code, 64)

    def test_wrapper_clears_environment_and_workflow_requires_trusted_issue(self):
        wrapper = (REPO / 'scripts/lifeos-audit-audiobooks-access.sh').read_text()
        self.assertIn('/usr/bin/env -i', wrapper)
        self.assertIn('/usr/bin/python3 -I', wrapper)
        self.assertIn('$# -eq 0 && $EUID -eq 0', wrapper)
        workflow = (REPO / '.github/workflows/lifeos-pi-deploy.yml').read_text()
        trusted = workflow.index('github.event.issue.author_association')
        audit = workflow.index("github.event.issue.title == 'LifeOS Deploy: audit-audiobooks-access'")
        self.assertLess(audit, trusted)
        self.assertIn('OWNER', workflow[audit:trusted])
        self.assertIn('MEMBER', workflow[audit:trusted])
        self.assertIn('COLLABORATOR', workflow[audit:trusted])


if __name__ == '__main__':
    unittest.main()
