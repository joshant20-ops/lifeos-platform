import json
import os
from pathlib import Path
import tempfile
import unittest
from governor.vpn_runtime_audit import capture_reports, router_url, wireguard_summary


class VPNRuntimeAuditTests(unittest.TestCase):
    def test_wireguard_metadata_never_exposes_peer_keys(self):
        result = wireguard_summary('51820', 'PRIVATE_PUBLIC_KEY 0', 'PRIVATE_PUBLIC_KEY 100 200')
        self.assertEqual(result['listen_port'], 51820)
        self.assertEqual(result['peers'][0]['received_bytes'], 100)
        self.assertIsNone(result['peers'][0]['handshake_age_seconds'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_capture_only_returns_completed_counts_not_raw_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'lifeos-vpn-check.fixture'
            file.write_text('PRIVATE_SENTINEL\nVPN_PACKETS_IN=0\nVPN_PACKETS_OUT=0\nVPN_PACKET_CHECK=FINISHED\n')
            file.chmod(0o600)
            result = capture_reports(root, os.getuid())
            self.assertTrue(result[0]['complete'])
            self.assertEqual(result[0]['in'], 0)
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertNotIn('fixture', json.dumps(result))
            file.chmod(0o644)
            self.assertEqual(capture_reports(root, os.getuid()), [])

    def test_router_requests_cannot_leave_the_gateway_or_include_credentials(self):
        self.assertEqual(router_url('http://192.0.2.1:1234/control', '192.0.2.1'), 'http://192.0.2.1:1234/control')
        for url in ('https://example.com/control', 'http://user:secret@192.0.2.1/control', 'file:///etc/passwd'):
            with self.assertRaises(ValueError):
                router_url(url, '192.0.2.1')


if __name__ == '__main__':
    unittest.main()
