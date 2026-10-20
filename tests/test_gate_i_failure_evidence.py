import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sanitize-gate-i-failure-evidence.py"
SPEC = importlib.util.spec_from_file_location("gate_i_failure_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_gate_i_evidence_keeps_known_error_code_and_drops_private_log_values():
    private = "person@example.invalid 192.168.1.25 AA:BB:CC:DD:EE:FF Bearer secret-value"
    evidence = MODULE.build_evidence(
        "ERROR=active_tower_lease_prevents_controller_restart:" + private + "\n"
        "GATEWAY_CHILD_RC=17\n"
        "GATEWAY_OPERATION=deploy-ha-control-bridge\n"
        "GATEWAY_PLATFORM_HEAD=" + "a" * 40 + "\n"
        "CONTROL_CURRENT_ISSUE=private title\n"
        "ERROR=unexpected user content " + private,
        17,
    )

    rendered = json.dumps(evidence)
    assert evidence["diagnostics"] == ["active_tower_lease_prevents_controller_restart"]
    assert evidence["exit_code"] == 17
    assert evidence["gateway"]["GATEWAY_CHILD_RC"] == 17
    assert evidence["gateway"]["GATEWAY_OPERATION"] == "deploy-ha-control-bridge"
    for secret in ("person@", "192.168.", "AA:BB:CC", "secret-value", "private title"):
        assert secret not in rendered


def test_gate_i_workflow_retains_only_sanitized_failure_artifact_and_preserves_failure():
    workflow = (ROOT / ".github" / "workflows" / "lifeos-pa-deploy.yml").read_text()
    gate = workflow[workflow.index("id: gate_i_bridge"):]
    gate = gate[:gate.index("Gate I — final live runtime consolidation acceptance")]
    assert "exit \"$rc\"" in gate
    assert "sanitize-gate-i-failure-evidence.py" in gate
    assert "steps.gate_i_bridge.outcome == 'failure'" in gate
    assert "actions/upload-artifact@v4" in gate
    assert "gate-i-control-bridge-sanitized.json" in gate
    assert "gate-i-control-bridge.log" not in gate.split("uses: actions/upload-artifact@v4", 1)[-1]
