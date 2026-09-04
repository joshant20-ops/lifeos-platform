import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path('scripts/clean-lifeos-control-legacy-executable-residue.sh')
TEXT = SCRIPT.read_text()


class LegacyResidueCleanerTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp = subprocess.run(['bash', '-n', str(SCRIPT)], text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_check_source_initialises_rel_before_using_it(self):
        marker = 'check_source(){\n'
        start = TEXT.index(marker) + len(marker)
        body = TEXT[start:TEXT.index('\n}\n', start)]
        self.assertIn('local rel expected path actual', body)
        self.assertIn('rel="$1"', body)
        self.assertIn('expected="$2"', body)
        self.assertIn('path="$CONTROL/$rel"', body)
        self.assertLess(body.index('rel="$1"'), body.index('path="$CONTROL/$rel"'))

    def test_nounset_startup_regression_for_local_dependency(self):
        snippet = r'''set -u
CONTROL=/tmp/control
f(){
  local rel expected path actual
  rel="$1"
  expected="$2"
  path="$CONTROL/$rel"
  printf '%s|%s|%s\n' "$rel" "$expected" "$path"
}
f broker/file abc
'''
        cp = subprocess.run(['bash', '-c', snippet], text=True, capture_output=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stdout.strip(), 'broker/file|abc|/tmp/control/broker/file')

    def test_runtime_paths_are_not_cleanup_targets(self):
        for forbidden in ('rm -rf "$CONTROL/jobs', 'rm -rf "$CONTROL/results', 'rm -rf "$CONTROL/state'):
            self.assertNotIn(forbidden, TEXT)
        self.assertIn('rm -rf "$CONTROL/broker" "$CONTROL/publisher" "$CONTROL/runner"', TEXT)


if __name__ == '__main__':
    unittest.main()
