import pathlib
import subprocess
import unittest

SCRIPT=pathlib.Path('scripts/diagnose-step11-live-terminal-policy.sh')
TEXT=SCRIPT.read_text()

class Step11LiveTerminalPolicyDiagnosticTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp=subprocess.run(['bash','-n',str(SCRIPT)],text=True,capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr)

    def test_read_only_hash_and_contract_checks(self):
        self.assertIn('/usr/local/libexec/job_records.py',TEXT)
        self.assertIn('sha256sum',TEXT)
        self.assertIn('LIVE_TERMINAL_CONTRACT=PASS',TEXT)
        self.assertIn('LIVE_MODULE_SYNC=STALE',TEXT)
        self.assertIn('LIVE_MODULE_SYNC=PASS',TEXT)
        self.assertNotIn('sudo ',TEXT)
        self.assertNotIn('install ',TEXT)
        self.assertNotIn('chmod ',TEXT)
        self.assertNotIn('systemctl ',TEXT)

if __name__=='__main__':
    unittest.main()
