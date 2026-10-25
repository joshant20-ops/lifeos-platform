import json
import unittest
from pathlib import Path
import tempfile
import struct
import sqlite3
from unittest.mock import MagicMock, patch
from governor.network_outage_audit import summarize_journal, runner_diagnostics, dns_probe, kuma_history


class NetworkOutageAuditTests(unittest.TestCase):
    def test_kuma_history_is_private_read_only_and_scoped_to_incident(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'kuma.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE monitor(id INTEGER,type TEXT,url TEXT,hostname TEXT)')
                db.execute('CREATE TABLE heartbeat(monitor_id INTEGER,status INTEGER,time TEXT,msg TEXT)')
                db.execute("INSERT INTO monitor VALUES(1,'http','http://private-name.lan/private',NULL)")
                db.execute("INSERT INTO heartbeat VALUES(1,0,'2026-10-23 20:40:00','Connection timed out PRIVATE_TOKEN')")
                db.execute("INSERT INTO heartbeat VALUES(1,0,'2026-10-25 20:40:00','PRIVATE_OUTSIDE')")
            before = path.read_bytes()
            result = kuma_history(path)
            self.assertEqual(result['samples'], 1)
            self.assertEqual(result['monitors'][0]['scope'], 'lan_name')
            self.assertEqual(result['monitors'][0]['down'], 1)
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertNotIn('private-name', json.dumps(result))
            self.assertEqual(path.read_bytes(), before)

    def test_dns_probe_reports_only_status_and_counts(self):
        for code, expected in ((0, 'NOERROR'), (3, 'NXDOMAIN'), (2, 'SERVFAIL')):
            stream = MagicMock()
            stream.__enter__.return_value = stream
            stream.recvfrom.return_value = (struct.pack('!6H', 0x4c4f, 0x8000 | code, 1, 1, 0, 0), ('192.0.2.1', 53))
            with patch('governor.network_outage_audit.socket.socket', return_value=stream):
                result = dns_probe('192.0.2.1', 'adguard.lan')
            self.assertEqual(result['status'], expected)
            self.assertNotIn('192.0.2.1', json.dumps(result))

    def test_runner_diagnostic_window_and_private_data_suppression(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Runner_20261023.log').write_text(
                '[2026-10-23 15:00:00Z] SocketException PRIVATE_OUTSIDE\n'
                '[2026-10-23 20:40:00Z] HttpRequestException PRIVATE_TOKEN\n'
                'SocketException: Name or service not known PRIVATE_HOST\n'
                '[2026-10-24 08:52:17Z] Listening for Jobs\n'
                '[2026-10-25 00:00:00Z] SocketException PRIVATE_OUTSIDE\n')
            output = runner_diagnostics(root)
            self.assertEqual(output['files_checked'], 1)
            self.assertFalse(output['scan_limit_reached'])
            self.assertNotIn('PRIVATE', json.dumps(output))
            self.assertIn('dns_lookup_error', {x['category'] for x in output['counts']})
            self.assertEqual(output['last'], '2026-10-24T08:52:17Z')

    def row(self, message, stamp='1792791000000000', unit='NetworkManager.service'):
        return json.dumps({'MESSAGE': message, '__REALTIME_TIMESTAMP': stamp, '_SYSTEMD_UNIT': unit})

    def test_only_categories_and_times_leave_private_journal_boundary(self):
        raw = '\n'.join((self.row('PRIVATE_SSID PRIVATE_TOKEN lost carrier 192.0.2.1'),
                         self.row('DHCP lease expired PRIVATE_SENTINEL'),
                         self.row('Temporary failure in name resolution PRIVATE_SENTINEL')))
        output = summarize_journal(raw)
        serialized = json.dumps(output)
        self.assertNotIn('PRIVATE', serialized)
        self.assertNotIn('192.0.2.1', serialized)
        self.assertEqual({x['category'] for x in output['counts']}, {'link_down', 'dhcp_failure', 'dns_failure'})
        self.assertEqual(output['records'], 3)

    def test_kernel_faults_and_runner_reconnect_are_not_conflated(self):
        kernel = summarize_journal(self.row('Under-voltage detected!'), kernel=True)
        self.assertEqual(kernel['events'][0]['group'], 'kernel')
        runner = summarize_journal(self.row('Listening for Jobs', unit='actions.runner.example.service'))
        self.assertEqual(runner['counts'], [{'group': 'runner', 'category': 'runner_connected', 'count': 1}])

    def test_truncated_malformed_or_nontext_records_do_not_leak_or_crash(self):
        raw = '\n'.join(('PRIVATE_BAD_JSON', self.row(['private']), self.row('private', stamp='bad')))
        self.assertEqual(summarize_journal(raw)['records'], 0)

    def test_repetitive_events_remain_bounded_but_counts_are_complete(self):
        raw = '\n'.join(self.row('lost carrier', str(1792791000000000 + i * 1000000)) for i in range(100))
        output = summarize_journal(raw)
        self.assertEqual(output['counts'][0]['count'], 100)
        self.assertEqual(len(output['events']), 6)


if __name__ == '__main__':
    unittest.main()
