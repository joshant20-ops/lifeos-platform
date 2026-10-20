from pathlib import Path
import importlib.util
import json

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location(
    "deploy_lifeos_dashboard",
    ROOT/"homeassistant"/"deploy-lifeos-dashboard.py",
)
DEPLOY=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


def test_lifeos_deployer_preserves_the_independent_control_registration():
    unrelated={"id":"dashboard_homelab","url_path":"dashboard-homelab","mode":"storage"}
    control={"id":"lifeos_control","url_path":"lifeos-control","mode":"storage","title":"LifeOS Control","custom":True}
    personal={"id":"dashboard_lifeos","url_path":"lifeos","mode":"storage","title":"Old title"}
    result=DEPLOY.reconcile_dashboard_registry([unrelated,control,personal])
    assert unrelated in result
    assert control in result
    assert [x for x in result if x.get("url_path")=="lifeos"] == [{
        "id":"dashboard_lifeos","show_in_sidebar":True,"icon":"mdi:home-automation",
        "title":"LifeOS","require_admin":False,"mode":"storage","url_path":"lifeos",
    }]


def test_lifeos_deployer_collapses_duplicate_personal_rows_without_dropping_control():
    control={"id":"lifeos_control","url_path":"lifeos-control","mode":"storage"}
    personal={"id":"dashboard_lifeos","url_path":"lifeos","mode":"storage"}
    result=DEPLOY.reconcile_dashboard_registry([personal,personal.copy(),control])
    assert sum(x.get("url_path")=="lifeos" for x in result)==1
    assert sum(x.get("url_path")=="lifeos-control" for x in result)==1


def test_lifeos_deployer_rejects_ambiguous_control_ownership():
    a={"id":"lifeos_control","url_path":"lifeos-control","mode":"storage"}
    b={"id":"other","url_path":"lifeos-control","mode":"storage"}
    try:
        DEPLOY.reconcile_dashboard_registry([a,b])
    except ValueError as exc:
        assert "inconsistent" in str(exc) or "Duplicate" in str(exc)
    else:
        raise AssertionError("inconsistent Control registration must fail closed")


def test_only_one_active_owner_deploys_each_lifeos_dashboard_role():
    workflows=ROOT/".github"/"workflows"
    active="\n".join(p.read_text(errors="ignore") for p in workflows.glob("*.yml"))
    assert "deploy-three-dashboard-roles.py" not in active
    assert "deploy-homelab-default-view.py" not in active
    assert sum("deploy-homelab-dashboard-v2.py" in p.read_text(errors="ignore") for p in workflows.glob("*.yml"))==1
    pa=(workflows/"lifeos-pa-deploy.yml").read_text()
    assert pa.index("accept-pa-governed-actions.py") < pa.index("deploy-ha-control-bridge")
    assert pa.index("deploy-ha-control-bridge") < pa.index("accept-pa-gate-i-runtime.py")
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"three-dashboard-role-deploy.yml").is_file()
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"deploy-three-dashboard-roles.py").is_file()
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"homelab-dashboard-deploy.yml").is_file()
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"deploy-homelab-default-view.py").is_file()



SANITIZER_SPEC = importlib.util.spec_from_file_location(
    "gate_i_failure_evidence",
    ROOT / "scripts" / "sanitize-gate-i-failure-evidence.py",
)
SANITIZER = importlib.util.module_from_spec(SANITIZER_SPEC)
assert SANITIZER_SPEC and SANITIZER_SPEC.loader
SANITIZER_SPEC.loader.exec_module(SANITIZER)


def test_gate_i_failure_evidence_retains_only_known_safe_diagnostics():
    private = "person@example.invalid 192.168.1.25 AA:BB:CC:DD:EE:FF Bearer secret-value"
    evidence = SANITIZER.build_evidence(
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


def test_gate_i_workflow_uploads_sanitized_evidence_only_on_failure():
    workflow = (ROOT / ".github" / "workflows" / "lifeos-pa-deploy.yml").read_text()
    gate = workflow[workflow.index("id: gate_i_bridge"):]
    gate = gate[:gate.index("Gate I — final live runtime consolidation acceptance")]
    assert 'exit "$rc"' in gate
    assert "sanitize-gate-i-failure-evidence.py" in gate
    assert "steps.gate_i_bridge.outcome == 'failure'" in gate
    upload = gate.split("uses: actions/upload-artifact@v4", 1)[-1]
    assert "gate-i-control-bridge-sanitized.json" in upload
    assert "gate-i-control-bridge.log" not in upload


ACCEPTANCE_SPEC = importlib.util.spec_from_file_location(
    "pa_governed_acceptance",
    ROOT / "scripts" / "accept-pa-governed-actions.py",
)
ACCEPTANCE = importlib.util.module_from_spec(ACCEPTANCE_SPEC)
assert ACCEPTANCE_SPEC and ACCEPTANCE_SPEC.loader
ACCEPTANCE_SPEC.loader.exec_module(ACCEPTANCE)


def test_ask_lifeos_provenance_matches_existing_source_message_ids():
    item = {"source_message_ids": ["message-1", "message-2"]}
    reply = "task ID: task-1; source refs: message-1, message-2"
    assert ACCEPTANCE.task_provenance_matches("task-1", item, reply)
    assert not ACCEPTANCE.task_provenance_matches(
        "task-2", item, reply
    )
    assert not ACCEPTANCE.task_provenance_matches(
        "task-1", item, "task ID: task-1; source refs: message-9"
    )
    assert not ACCEPTANCE.task_provenance_matches(
        "task-1", {"source_message_ids": []}, reply
    )
