from pathlib import Path
import importlib.util

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
    assert active.count("deploy-homelab-dashboard-v2.py")==1
    pa=(workflows/"lifeos-pa-deploy.yml").read_text()
    assert pa.index("accept-pa-governed-actions.py") < pa.index("deploy-ha-control-bridge")
    assert pa.index("deploy-ha-control-bridge") < pa.index("accept-pa-gate-i-runtime.py")
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"three-dashboard-role-deploy.yml").is_file()
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"deploy-three-dashboard-roles.py").is_file()
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"homelab-dashboard-deploy.yml").is_file()
    assert (ROOT/"archive"/"superseded-dashboard-owners"/"deploy-homelab-default-view.py").is_file()


def test_existing_task_publisher_audit_remains_a_single_writer():
    from tests.test_pa_no_duplicate_authorities import test_only_one_active_personal_task_publisher
    test_only_one_active_personal_task_publisher()
