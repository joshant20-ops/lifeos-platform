import json
import unittest
from governor.network_outage_audit import summarize_journal


class NetworkOutageAuditTests(unittest.TestCase):
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
