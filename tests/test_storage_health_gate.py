import unittest
from governor.storage_health_gate import HealthGate, HealthUnavailable


class HealthGateTests(unittest.TestCase):
    def gate(self, probe):
        now = [0.0]
        gate = HealthGate(probe, clock=lambda: now[0])
        return gate, now

    def test_requires_initial_fresh_success(self):
        gate, now = self.gate(lambda: {'dns': True, 'internet': True})
        with self.assertRaises(HealthUnavailable):
            gate.guard()
        gate.sample()
        gate.guard()
        now[0] = 3
        with self.assertRaises(HealthUnavailable):
            gate.guard()

    def test_outage_latches_even_after_recovery(self):
        checks = {'dns': True, 'internet': True}
        gate, _ = self.gate(lambda: checks)
        gate.sample()
        checks['dns'] = False
        gate.sample()
        checks['dns'] = True
        gate.sample()
        with self.assertRaises(HealthUnavailable):
            gate.guard()

    def test_errors_empty_and_truthy_non_boolean_checks_fail_closed(self):
        def error():
            raise OSError('probe failed')
        for probe in (error, lambda: {}, lambda: {'dns': 'true'}):
            gate, _ = self.gate(probe)
            gate.sample()
            with self.assertRaises(HealthUnavailable):
                gate.guard()

    def test_slow_probe_is_not_fresh(self):
        gate, now = self.gate(lambda: {'dns': True})
        def slow():
            now[0] += 4
            return {'dns': True}
        gate.probe = slow
        gate.sample()
        with self.assertRaises(HealthUnavailable):
            gate.guard()

    def test_closed_gate_cannot_authorise_or_restart(self):
        gate, _ = self.gate(lambda: {'dns': True})
        gate.sample()
        gate.close()
        with self.assertRaises(HealthUnavailable):
            gate.guard()
        with self.assertRaises(HealthUnavailable):
            gate.start()

    def test_background_monitor_latches_failure(self):
        import threading
        failed_sample = threading.Event()
        calls = [0]
        def probe():
            calls[0] += 1
            if calls[0] > 1:
                failed_sample.set()
                return {'dns': False}
            return {'dns': True}
        gate = HealthGate(probe, interval=0.01, max_age=1).start()
        try:
            self.assertTrue(failed_sample.wait(timeout=1))
            # Taking one more failed sample removes scheduling ambiguity between
            # the callback event and publication of the latched result.
            gate.sample()
            with self.assertRaises(HealthUnavailable):
                gate.guard()
        finally:
            gate.close()
        self.assertFalse(gate.thread.is_alive())
