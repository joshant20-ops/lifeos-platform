import importlib.machinery
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "homelab/live/usr/local/sbin/lifeos-deploy-gateway"
WORKFLOW = ROOT / ".github/workflows/lifeos-pi-deploy.yml"
DIAGNOSTIC = ROOT / "scripts/lifeos-tower-wol-packet-diagnostic.py"


def load_gateway():
    loader = importlib.machinery.SourceFileLoader("wol_issue_gateway", str(GATEWAY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TowerWolIssueTriggerTests(unittest.TestCase):
    def test_diagnostic_holds_one_lease_through_bounded_retry_window(self):
        loader = importlib.machinery.SourceFileLoader("tower_wol_diagnostic", str(DIAGNOSTIC))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        diagnostic = importlib.util.module_from_spec(spec)
        loader.exec_module(diagnostic)

        self.assertEqual(diagnostic.LEASE_WINDOW_SECONDS, 120)
        self.assertGreater(diagnostic.LEASE_TTL_SECONDS, diagnostic.LEASE_WINDOW_SECONDS)
        self.assertFalse(diagnostic.wake_window_complete(0.0, 2.0, False))
        self.assertFalse(diagnostic.wake_window_complete(0.0, 119.9, False))
        self.assertTrue(diagnostic.wake_window_complete(0.0, 120.0, False))
        self.assertTrue(diagnostic.wake_window_complete(0.0, 8.0, True))

    def test_tower_wol_operations_are_fixed_gateway_entries(self):
        gateway = load_gateway()
        self.assertEqual(gateway.OPS["inspect-tower-wol"], {
            "script": "scripts/lifeos-inspect-tower-wol.sh", "privileged": True
        })
        self.assertEqual(gateway.OPS["capture-tower-wol"], {
            "script": "scripts/lifeos-capture-tower-wol.sh", "privileged": True
        })
        self.assertFalse(any(
            "wol" in key and key not in {"inspect-tower-wol", "capture-tower-wol"}
            for key in gateway.OPS
        ))

    def test_gateway_accepts_only_inspect_or_fingerprint_bound_capture(self):
        gateway = load_gateway()
        fingerprint = "a" * 64
        self.assertEqual(gateway.parse_request(["inspect-tower-wol"]), ("inspect-tower-wol", []))
        self.assertEqual(
            gateway.parse_request(["capture-tower-wol", fingerprint, "37782885765"]),
            ("capture-tower-wol", [fingerprint, "37782885765"]),
        )

    def test_gateway_rejects_arbitrary_or_malformed_operation_injection(self):
        gateway = load_gateway()
        invalid = [
            ["anything"],
            ["deploy-p0-resilience;id"],
            ["inspect-tower-wol", "extra"],
            ["capture-tower-wol"],
            ["capture-tower-wol", "a" * 63, "1"],
            ["capture-tower-wol", "a" * 64 + ";id", "1"],
            ["capture-tower-wol", "A" * 64, "1"],
            ["capture-tower-wol", "a" * 64, "1;id"],
            ["capture-tower-wol", "a" * 64, "1", "extra"],
        ]
        for argv in invalid:
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as exc:
                gateway.parse_request(argv)
            self.assertEqual(exc.exception.code, 64)

    def test_issue_trigger_titles_are_exact_and_diagnostic_evidence_is_reported(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("github.event.issue.title == 'LifeOS Deploy: inspect-tower-wol'", workflow)
        self.assertIn("github.event.issue.title == 'LifeOS Deploy: capture-tower-wol'", workflow)
        self.assertIn(
            "inspect-tower-wol', 'capture-tower-wol'].includes(process.env.LIFEOS_OPERATION)",
            workflow,
        )
        self.assertNotIn("github.event.issue.title }} ", workflow)


if __name__ == "__main__":
    unittest.main()
