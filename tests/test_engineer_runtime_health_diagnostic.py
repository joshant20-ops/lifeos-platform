import pathlib
import subprocess
import unittest

SCRIPT=pathlib.Path('scripts/diagnose-engineer-runtime-health.sh')
TEXT=SCRIPT.read_text()

class EngineerRuntimeHealthDiagnosticTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp=subprocess.run(['bash','-n',str(SCRIPT)],text=True,capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr)

    def test_is_read_only(self):
        forbidden=('systemctl restart','systemctl start','systemctl stop','chmod ','chown ','rm ','mv ','cp ','install ','tee ','git reset','git checkout')
        for token in forbidden:
            self.assertNotIn(token,TEXT)
        self.assertIn('MUTATION_PERFORMED=NO',TEXT)

    def test_separates_process_and_dependency_health(self):
        self.assertIn('ENGINEER_HEALTH',TEXT)
        self.assertIn('ENGINEER_MODELS',TEXT)
        self.assertIn('OLLAMA_TAGS',TEXT)
        self.assertIn('http://192.168.0.201:11434/api/tags',TEXT)
        self.assertIn('lifeos-engineer.service',TEXT)
        self.assertIn('ss -ltnp',TEXT)

    def test_preserves_deployment_evidence(self):
        self.assertIn('engineer-current-20260904-v3.json',TEXT)
        self.assertIn('rollback_result',TEXT)
        self.assertIn('backup_location',TEXT)

if __name__=='__main__':
    unittest.main()
