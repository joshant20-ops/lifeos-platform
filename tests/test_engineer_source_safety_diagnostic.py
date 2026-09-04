import pathlib
import subprocess
import unittest

SCRIPT=pathlib.Path('scripts/diagnose-engineer-source-safety.sh')
TEXT=SCRIPT.read_text()

class EngineerSourceSafetyDiagnosticTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp=subprocess.run(['bash','-n',str(SCRIPT)],text=True,capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr)

    def test_reproduces_broker_safety_predicate(self):
        self.assertIn('REPO_UID="$(stat -c %u "$PLATFORM")"',TEXT)
        self.assertIn('[[ "$uid" == "$REPO_UID" ]]',TEXT)
        self.assertIn('mode_num=$((8#$mode))',TEXT)
        self.assertIn('(( mode_num & 0022 ))',TEXT)
        self.assertIn('[[ -f "$path" && ! -L "$path" ]]',TEXT)

    def test_checks_exact_git_bytes_without_mutation(self):
        self.assertIn('git -C "$PLATFORM" show "$HEAD:$rel" | sha256sum',TEXT)
        self.assertIn('CHECKSUM_MATCH=',TEXT)
        for forbidden in ('chown ','chmod ','install ','rm -f ','mv ','cp '):
            self.assertNotIn(forbidden,TEXT)
        self.assertIn('MUTATION_PERFORMED=NO',TEXT)

    def test_reports_all_three_deploy_sources_and_failed_evidence(self):
        for rel in ('governor/autonomous_agent.py','governor/target_identity.py','governor/engineer_backend.py'):
            self.assertIn(rel,TEXT)
        self.assertIn('engineer-current-20260904-v2',TEXT)
        self.assertIn('BROKER_SOURCE_SAFETY=',TEXT)

if __name__=='__main__':
    unittest.main()
