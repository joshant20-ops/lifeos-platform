import base64
import importlib.machinery
import json


def load(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_BACKLOG_STATE", str(tmp_path))
    return importlib.machinery.SourceFileLoader("hierarchical_backlog_test", "governor/backlog_runner.py").load_module()


def sample_plan():
    return {"milestones": [
        {"id": "design", "title": "Design", "mandatory": True, "verification": "contract tests pass", "targets": [
            {"id": "design.contract", "title": "Contract", "mandatory": True, "depends_on": [],
             "acceptance_criteria": ["schema validates"], "runtime_verification_required": False}]},
        {"id": "prove", "title": "Prove", "mandatory": True, "verification": "runtime proof", "targets": [
            {"id": "prove.runtime", "title": "Runtime proof", "mandatory": True, "depends_on": ["design.contract"],
             "acceptance_criteria": ["restart resumes", "runtime evidence recorded"], "runtime_verification_required": True}]},
    ]}


def evidence(**fields):
    return "\n".join(f"{key}={value}" for key, value in fields.items())


def test_substantial_plan_is_persisted_and_resumes_at_small_target(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    encoded = base64.b64encode(json.dumps(sample_plan()).encode()).decode()
    entry = {}
    progress = module.apply_plan_result(entry, {"phase": "planning", "issue": 27, "job_id": "plan"},
        {"iterations": [{"evidence": evidence(PLAN_JSON_B64=encoded)}]})
    assert progress == {"completed_targets": 0, "total_targets": 2, "current_target": "design.contract", "state": "IN_PROGRESS"}
    state = module.empty_state(); state["issues"]["27"] = entry; module.save_state(state)
    resumed = module.load_state()["issues"]["27"]["plan"]
    assert module.next_target(resumed)["id"] == "design.contract"
    assert module.next_target(resumed)["acceptance_criteria"] == ["schema validates"]


def test_later_failure_preserves_pass_and_parent_stays_in_progress(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); plan = module.validate_plan(sample_plan(), 27)
    entry = {"plan": plan}; first = module.next_target(plan); first["state"] = "IN_PROGRESS"; first["attempts"] = 1
    module.apply_plan_result(entry, {"phase": "target", "issue": 27, "job_id": "one", "target_id": first["id"]},
        {"iterations": [{"evidence": evidence(TARGET_STATE="PASS", TARGET_EVIDENCE="unit tests passed")}]})
    second = module.next_target(plan); second["state"] = "IN_PROGRESS"; second["attempts"] = 1
    result = module.apply_plan_result(entry, {"phase": "target", "issue": 27, "job_id": "two", "target_id": second["id"]},
        {"iterations": [{"evidence": evidence(TARGET_STATE="PASS", TARGET_EVIDENCE="built only")}]})
    assert first["state"] == "PASS"
    assert second["state"] == "FAILED"  # runtime-required targets need explicit runtime proof
    assert result["state"] == "IN_PROGRESS"
    assert result["completed_targets"] == 1


def test_mandatory_milestones_gate_parent_but_optional_does_not(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); raw = sample_plan()
    raw["milestones"].append({"id": "stretch", "mandatory": False, "targets": [{"id": "stretch.one",
        "mandatory": False, "depends_on": [], "acceptance_criteria": ["optional"], "runtime_verification_required": False}]})
    plan = module.validate_plan(raw, 27)
    for target in module.plan_targets(plan):
        if target["mandatory"]: target["state"] = "PASS"
    module.refresh_plan(plan)
    assert plan["state"] == "PASS"
    assert plan["milestones"][-1]["state"] == "IN_PROGRESS"


def test_invalid_plan_without_acceptance_criteria_is_rejected(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch); raw = sample_plan()
    raw["milestones"][0]["targets"][0]["acceptance_criteria"] = []
    try: module.validate_plan(raw, 27)
    except ValueError as exc: assert "acceptance criteria" in str(exc)
    else: raise AssertionError("invalid plan accepted")
