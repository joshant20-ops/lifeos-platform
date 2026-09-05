import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "homelab/live/usr/local/sbin/lifeos-deploy-gateway"
CLOSURE = ROOT / "scripts/lifeos-step11-live-closure.sh"
WORKFLOW = ROOT / ".github/workflows/lifeos-stage3-gateway-refresh.yml"


class Step11LiveClosureContract(unittest.TestCase):
    def test_closure_script_is_syntactically_valid_and_narrow(self):
        subprocess.run(["bash", "-n", str(CLOSURE)], check=True)
        text = CLOSURE.read_text()
        self.assertIn("LIVE=/usr/local/libexec/job_records.py", text)
        self.assertIn("SERVICE=lifeos-autonomous-agent.service", text)
        self.assertIn('install -o root -g root -m 0644 "$SOURCE" "$TMP"', text)
        self.assertIn('systemctl restart "$SERVICE"', text)
        self.assertIn('scripts/diagnose-step11-live-terminal-policy.sh', text)
        self.assertIn('STEP_11=PASS', text)
        self.assertIn('NEXT_REQUIRED=step11_closed', text)
        self.assertNotIn("eval ", text)
        self.assertNotIn("rm -rf", text)
        self.assertNotIn("sudo ", text)

    def test_gateway_retains_exact_step11_operation(self):
        text = GATEWAY.read_text()
        self.assertIn("'step11-live-closure': {", text)
        self.assertIn("'script': 'scripts/lifeos-step11-live-closure.sh'", text)
        self.assertIn("'privileged': True", text)
        self.assertIn("sys.argv[1] not in OPS", text)
        self.assertNotIn("shell=True", text)
        self.assertNotIn("eval(", text)

    def test_self_hosted_workflow_refreshes_gateway_then_closes_step11(self):
        text = WORKFLOW.read_text()
        refresh = text.index("lifeos-deploy-gateway deploy-ha-control-bridge")
        closure = text.index("lifeos-deploy-gateway step11-live-closure")
        self.assertLess(refresh, closure)
        for marker in (
            "STEP_11=PASS", "LIVE_MODULE_SYNC=PASS", "PASS_STOP=PASS",
            "GENUINE_BLOCKED_STOP=PASS", "REPEATED_FAILURE_STOP=PASS",
            "ITERATION_LIMIT_STOP=PASS", "NON_TERMINAL_RETRY=PASS",
            "AUTONOMOUS_AGENT_HEALTH=PASS", "NEXT_REQUIRED=step11_closed",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
