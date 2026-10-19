from pathlib import Path
import importlib.machinery
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/lifeos-pi-deploy.yml"
GATEWAY = ROOT / "homelab/live/usr/local/sbin/lifeos-deploy-gateway"
WRAPPER = ROOT / "scripts/lifeos-paperless-runtime-audit.sh"
DIAGNOSTIC = ROOT / "governor/paperless_runtime_diagnostic.py"


def load_gateway():
    loader = importlib.machinery.SourceFileLoader("paperless_audit_gateway", str(GATEWAY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PaperlessReadOnlyAuditTriggerTests(unittest.TestCase):
    def test_existing_pi_workflow_dispatches_only_named_audit_operation(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("- audit-paperless-runtime", workflow)
        self.assertIn(
            "github.event.issue.title == 'LifeOS Deploy: audit-paperless-runtime'",
            workflow,
        )
        self.assertIn(
            "github.event.issue.title == 'LifeOS Deploy: audit-paperless-runtime' && 'audit-paperless-runtime'",
            workflow,
        )
        self.assertIn(
            '|| "$LIFEOS_OPERATION" == "audit-paperless-runtime" || "$LIFEOS_OPERATION" == "restore-paperless" ]]; then',
            workflow,
        )

    def test_operation_uses_fixed_root_gateway_entry_and_script(self):
        gateway = load_gateway()
        self.assertEqual(
            gateway.OPS["audit-paperless-runtime"],
            {
                "script": "scripts/lifeos-paperless-runtime-audit.sh",
                "privileged": True,
            },
        )
        self.assertEqual(gateway.parse_request(["audit-paperless-runtime"]), ("audit-paperless-runtime", []))
        with self.assertRaises(SystemExit) as exc:
            gateway.parse_request(["audit-paperless-runtime", "arbitrary-command"])
        self.assertEqual(exc.exception.code, 64)

    def test_gateway_wrapper_runs_the_existing_fixed_field_diagnostic(self):
        wrapper = WRAPPER.read_text()
        self.assertIn("set -Eeuo pipefail", wrapper)
        self.assertIn(
            "exec python3 /home/joshan/lifeos-platform/governor/paperless_runtime_diagnostic.py",
            wrapper,
        )
        self.assertIn('PAPERLESS_AUDIT_MUTATIONS=NONE', DIAGNOSTIC.read_text())

    def test_restore_uses_exact_issue_route_and_refreshes_root_gateway(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("LifeOS Deploy: restore-paperless", workflow)
        self.assertIn("github.event.issue.title == 'LifeOS Deploy: restore-paperless' && 'restore-paperless'", workflow)
        self.assertIn('|| "$LIFEOS_OPERATION" == "restore-paperless" ]]; then', workflow)
        gateway = load_gateway()
        self.assertEqual(
            gateway.OPS["restore-paperless"],
            {"script": "scripts/lifeos-paperless-restore.sh", "privileged": True},
        )
        self.assertEqual(gateway.parse_request(["restore-paperless"]), ("restore-paperless", []))

    def test_audit_is_serialized_and_uses_existing_pi_runner(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("group: lifeos-pi5-deploy", workflow)
        self.assertIn("runs-on: [self-hosted, linux, ARM64, lifeos-pi5]", workflow)
        self.assertIn("scripts/lifeos-install-github-runner-gateway.sh", workflow)


if __name__ == "__main__":
    unittest.main()
