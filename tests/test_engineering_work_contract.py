import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate-engineering-work-contract.py"
FIXTURE = REPO / "governor" / "contracts" / "examples" / "stage10-smoke.json"


class EngineeringWorkContractTests(unittest.TestCase):
    def run_contract(self, data):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(data, handle)
            path = handle.name
        try:
            return subprocess.run(
                ["python3", str(VALIDATOR), path],
                text=True,
                capture_output=True,
                check=False,
            )
        finally:
            Path(path).unlink(missing_ok=True)

    def test_valid_planned_contract_passes(self):
        data = json.loads(FIXTURE.read_text())
        cp = self.run_contract(data)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("CONTRACT_VALIDATION=PASS", cp.stdout)

    def test_required_deploy_without_gateway_fails(self):
        data = json.loads(FIXTURE.read_text())
        data["deployment"]["gateway_operation"] = None
        cp = self.run_contract(data)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("deployment_gateway_operation_required", cp.stdout)

    def test_pass_without_runtime_evidence_fails(self):
        data = json.loads(FIXTURE.read_text())
        data["state"] = "PASS"
        data["tests"][0]["result"] = "PASS"
        data["runtime_verification"]["result"] = "PENDING"
        data["evidence"]["records"] = [{"kind": "deployment", "value": "proof"}]
        cp = self.run_contract(data)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("pass_requires_runtime_verification", cp.stdout)

    def test_blocked_without_reason_fails(self):
        data = json.loads(FIXTURE.read_text())
        data["state"] = "BLOCKED"
        data["blocker"] = None
        cp = self.run_contract(data)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("blocked_requires_blocker", cp.stdout)


if __name__ == "__main__":
    unittest.main()
