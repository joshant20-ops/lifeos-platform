import contextlib
import io
import signal
import unittest
from unittest.mock import MagicMock, call, patch

from governor import storage_root_allocation as probe


class RootAllocationTests(unittest.TestCase):
    def run_probe(self, states, clock=(0, 1, 9, 10, 11, 12)):
        child = MagicMock()
        output = io.StringIO()

        def scan(*, guard):
            guard(process=child)
            return 0

        with patch.object(probe.os, "geteuid", return_value=0), \
             patch.object(probe, "connection_inputs", return_value=("resolver", "public")), \
             patch.object(probe, "health_checks", side_effect=states), \
             patch.object(probe.time, "monotonic", side_effect=clock), \
             patch.object(probe, "audit", side_effect=scan), \
             contextlib.redirect_stdout(output):
            result = probe.main()
        return result, child.send_signal.call_args_list, output.getvalue()

    def test_fresh_probe_resumes_traversal_and_requires_final_health(self):
        states = [{"checks": True}, {"checks": True}, {"checks": False}]
        result, signals, output = self.run_probe(states)
        self.assertEqual(result, 2)
        self.assertEqual(signals, [call(signal.SIGSTOP), call(signal.SIGCONT)])
        self.assertNotIn("=PASS", output)

    def test_failed_probe_leaves_traversal_stopped_for_cleanup(self):
        result, signals, output = self.run_probe([{"checks": True}, {"checks": False}])
        self.assertEqual(result, 2)
        self.assertEqual(signals, [call(signal.SIGSTOP)])
        self.assertNotIn("=PASS", output)

    def test_probe_without_freshness_headroom_does_not_resume(self):
        result, signals, output = self.run_probe(
            [{"checks": True}, {"checks": True}], clock=(0, 1, 9, 21),
        )
        self.assertEqual(result, 2)
        self.assertEqual(signals, [call(signal.SIGSTOP)])
        self.assertNotIn("=PASS", output)
