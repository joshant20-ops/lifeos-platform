"""Fail-closed canonical checkout checks; no Pi or private data required."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pa_runtime_gate', Path(__file__).resolve().parents[1] / 'scripts/accept-pa-gate-i-runtime.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class CheckoutTests(unittest.TestCase):
    def verify(self, head='same', origin='same', dirty='', errors=(0, 0, 0)):
        results = [subprocess.CompletedProcess([], code, stdout=value, stderr='private diagnostic')
                   for code, value in zip(errors, (head, origin, dirty))]
        with patch.object(gate, 'run', side_effect=results) as run, patch('builtins.print') as output:
            if head != origin or dirty or any(errors):
                with self.assertRaisesRegex(RuntimeError, 'CANONICAL_CLEAN_CHECKOUT'):
                    gate.verify_canonical_checkout()
            else:
                gate.verify_canonical_checkout()
            for call in run.call_args_list:
                self.assertEqual(call.args[0][:4], ['runuser', '-u', 'joshan', '--'])
            self.assertNotIn('private diagnostic', str(output.call_args_list))

    def test_clean_matching_checkout_passes_as_owner(self):
        self.verify()

    def test_different_head_or_any_dirt_is_rejected(self):
        self.verify(origin='different')
        self.verify(dirty=' M tracked.py')
        self.verify(dirty='?? untracked.txt')

    def test_failed_git_reads_cannot_look_clean(self):
        for errors in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            self.verify(errors=errors)


if __name__ == '__main__':
    unittest.main()
