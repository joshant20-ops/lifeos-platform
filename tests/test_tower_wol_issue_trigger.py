import importlib.machinery
import importlib.util
import pathlib

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "homelab/live/usr/local/sbin/lifeos-deploy-gateway"
WORKFLOW = ROOT / ".github/workflows/lifeos-pi-deploy.yml"


def load_gateway():
    loader = importlib.machinery.SourceFileLoader("wol_issue_gateway", str(GATEWAY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_tower_wol_operations_are_fixed_gateway_entries():
    gateway = load_gateway()
    assert gateway.OPS["inspect-tower-wol"] == {
        "script": "scripts/lifeos-inspect-tower-wol.sh", "privileged": True
    }
    assert gateway.OPS["capture-tower-wol"] == {
        "script": "scripts/lifeos-capture-tower-wol.sh", "privileged": True
    }
    assert not any("wol" in key and key not in {"inspect-tower-wol", "capture-tower-wol"} for key in gateway.OPS)


def test_gateway_accepts_only_inspect_or_fingerprint_bound_capture():
    gateway = load_gateway()
    fingerprint = "a" * 64
    assert gateway.parse_request(["inspect-tower-wol"]) == ("inspect-tower-wol", [])
    assert gateway.parse_request(["capture-tower-wol", fingerprint, "37782885765"]) == (
        "capture-tower-wol", [fingerprint, "37782885765"]
    )


@pytest.mark.parametrize("argv", [
    ["anything"],
    ["deploy-p0-resilience"],
    ["inspect-tower-wol", "extra"],
    ["capture-tower-wol"],
    ["capture-tower-wol", "a" * 63, "1"],
    ["capture-tower-wol", "a" * 64 + ";id", "1"],
    ["capture-tower-wol", "A" * 64, "1"],
    ["capture-tower-wol", "a" * 64, "1;id"],
    ["capture-tower-wol", "a" * 64, "1", "extra"],
])
def test_gateway_rejects_arbitrary_or_malformed_operation_injection(argv):
    gateway = load_gateway()
    with pytest.raises(SystemExit) as exc:
        gateway.parse_request(argv)
    assert exc.value.code == 64


def test_issue_trigger_titles_are_exact_and_diagnostic_evidence_is_reported():
    workflow = WORKFLOW.read_text()
    assert "github.event.issue.title == 'LifeOS Deploy: inspect-tower-wol'" in workflow
    assert "github.event.issue.title == 'LifeOS Deploy: capture-tower-wol'" in workflow
    assert "inspect-tower-wol', 'capture-tower-wol'].includes(process.env.LIFEOS_OPERATION)" in workflow
    assert "github.event.issue.title }} " not in workflow
