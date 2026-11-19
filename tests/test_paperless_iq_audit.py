import unittest
from governor.paperless_iq_audit import CHILD, sanitise
import json


class IQAuditTests(unittest.TestCase):
    def test_safe_aggregate_packet(self):
        value = {'mutations': 'NONE', 'result': 'READ_ONLY_COMPLETE', 'pending_total': 10,
                 'db_auto_apply': False, 'source_main_sha256': 'a' * 64}
        self.assertEqual(sanitise(json.dumps(value)), value)

    def test_private_or_unbounded_output_is_rejected(self):
        base = {'mutations': 'NONE', 'result': 'READ_ONLY_COMPLETE'}
        for item in ({'document_text': 'private'}, {'db_auto_apply': 'secret'},
                     {'pending_total': True}, {'pending_total': -1},
                     {'source_main_sha256': 'private'}, {'result': 'private'},
                     {'mutations': 'WRITE'}):
            with self.subTest(keys=list(item)), self.assertRaises(ValueError):
                sanitise(json.dumps({**base, **item}))

    def test_child_compiles_and_does_not_start_application(self):
        compile(CHILD, 'fixed-iq-audit', 'exec')
        self.assertIn('?mode=ro', CHILD)
        self.assertIn('PRAGMA query_only=ON', CHILD)
        self.assertNotIn('import backend', CHILD)
        self.assertIn('signal.alarm(35)', CHILD)


if __name__ == '__main__':
    unittest.main()
