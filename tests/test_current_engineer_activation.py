import pathlib
import subprocess
import unittest

SCRIPT=pathlib.Path('scripts/activate-current-engineer-runtime.sh')
TEXT=SCRIPT.read_text()


class CurrentEngineerActivationTests(unittest.TestCase):
    def test_shell_syntax(self):
        cp=subprocess.run(['bash','-n',str(SCRIPT)],text=True,capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr)

    def test_pins_migrated_live_broker_hash(self):
        self.assertIn('a9da48216ad261631be29216e001d52306f6981fb07e35727d8b38b92f02b309',TEXT)
        self.assertIn('live broker hash differs from approved migrated broker',TEXT)

    def test_requires_clean_published_main(self):
        self.assertIn('rev-parse refs/remotes/origin/main',TEXT)
        self.assertIn('status --porcelain --untracked-files=no',TEXT)
        self.assertIn('platform is not checked out at published main',TEXT)

    def test_binds_approval_and_request_to_canonical_target_identity(self):
        self.assertIn('readonly IDENTITY=/etc/lifeos-control/identity.json',TEXT)
        self.assertIn("d.get('target_id')",TEXT)
        self.assertIn('TARGET="$(python3 - "$IDENTITY"',TEXT)
        self.assertNotIn('readonly TARGET=pi5',TEXT)
        self.assertIn("'target':target",TEXT)
        self.assertIn("assert d['target']==target",TEXT)
        self.assertIn('TARGET_ID=',TEXT)

    def test_retry_uses_new_job_id_and_preserves_prior_evidence(self):
        self.assertIn('readonly JOB_ID=engineer-current-20260904-v3',TEXT)
        self.assertNotIn('rm -f "$APPROVAL"',TEXT)
        self.assertNotIn('rm -f "$AUDIT"',TEXT)

    def test_exact_observed_metadata_repair_is_narrow(self):
        self.assertIn('readonly BACKEND_REL=governor/engineer_backend.py',TEXT)
        self.assertIn("if mode != 0o775",TEXT)
        self.assertIn('backend mode changed from observed 775',TEXT)
        self.assertIn('chmod 0755 "$PLATFORM/$BACKEND_REL"',TEXT)
        self.assertIn('METADATA_REPAIR=governor/engineer_backend.py:0775->0755',TEXT)
        self.assertNotIn('chown ',TEXT)
        self.assertNotIn('chmod -R',TEXT)

    def test_reproduces_broker_source_safety_before_approval(self):
        self.assertIn('stat.S_ISREG(st.st_mode)',TEXT)
        self.assertIn('st.st_uid==repo_uid',TEXT)
        self.assertIn('not (st.st_mode & 0o022)',TEXT)
        self.assertIn('actual==expected',TEXT)
        self.assertLess(TEXT.index("stage 2 'EXACT SOURCE SAFETY REPAIR AND REVALIDATION'"),
                        TEXT.index("stage 3 'CREATE FRESH ROOT-OWNED APPROVAL'"))

    def test_approval_is_exact_and_root_owned(self):
        for rel in ('governor/autonomous_agent.py','governor/target_identity.py','governor/engineer_backend.py'):
            self.assertIn(rel,TEXT)
        self.assertIn("'operation':'deploy-engineer-runtime'",TEXT)
        self.assertIn("os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)",TEXT)
        self.assertIn('os.chown(path,0,0)',TEXT)

    def test_uses_existing_bounded_broker_only(self):
        self.assertIn("'operation':'deploy-engineer-runtime'",TEXT)
        self.assertIn('/run/lifeos-root-broker.sock',TEXT)
        self.assertNotIn('cp "$PLATFORM/governor/engineer_backend.py"',TEXT)
        self.assertNotIn('install "$PLATFORM/governor/engineer_backend.py"',TEXT)

    def test_validates_audit_live_hashes_health_and_fail_closed(self):
        self.assertIn("d['deployment_result']=='PASS'",TEXT)
        self.assertIn('lifeos-autonomous-agent',TEXT)
        self.assertIn('lifeos-engineer',TEXT)
        self.assertIn('http://127.0.0.1:8793/health',TEXT)
        self.assertIn('OPEN_WEBUI_ACCEPTANCE=PASS',TEXT)
        self.assertIn('MALFORMED_REQUEST_REJECTION=PASS',TEXT)

    def test_machine_readable_completion(self):
        self.assertIn("FINAL_STATUS=PASS",TEXT)
        self.assertIn("NEXT_REQUIRED=phase1_closure_review",TEXT)


if __name__=='__main__':
    unittest.main()
