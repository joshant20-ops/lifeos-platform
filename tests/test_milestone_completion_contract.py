import importlib.machinery
import os
import pathlib


SOURCE = pathlib.Path("governor/autonomous_agent.py")


def load_agent(tmp_path):
    previous = os.environ.get("LIFEOS_AGENT_STATE")
    os.environ["LIFEOS_AGENT_STATE"] = str(tmp_path / "state")
    try:
        return importlib.machinery.SourceFileLoader(
            f"milestone_agent_{tmp_path.name}", str(SOURCE)
        ).load_module()
    finally:
        if previous is None:
            os.environ.pop("LIFEOS_AGENT_STATE", None)
        else:
            os.environ["LIFEOS_AGENT_STATE"] = previous


def contract_job(module, tmp_path):
    module.ROOT = tmp_path / "state"
    return module.new_job(
        """Implement a multi-stage change.

Final status must explicitly report:
IMPLEMENTATION=
DEPLOYMENT=
INDEPENDENT_VERIFICATION=
"""
    )


def test_successful_iteration_does_not_finish_incomplete_milestone(tmp_path):
    module = load_agent(tmp_path)
    job = contract_job(module, tmp_path)
    decision = module.milestone_decision(
        job,
        {"verdict": "PASS", "reason": "implementation tests passed"},
        "IMPLEMENTATION=PASS\nDEPLOYMENT=PENDING\nINDEPENDENT_VERIFICATION=NOT_VERIFIED\n",
    )
    assert decision["iteration_result"] == "PASS"
    assert decision["milestone_result"] == "RETRY"
    assert "DEPLOYMENT" in decision["next_instruction"]


def test_retry_continues_to_next_useful_phase(tmp_path):
    module = load_agent(tmp_path)
    job = contract_job(module, tmp_path)
    decision = module.milestone_decision(
        job,
        {"verdict": "RETRY", "next_instruction": "run shadow deployment"},
        "IMPLEMENTATION=PASS\nDEPLOYMENT=NOT_STARTED\n",
    )
    assert decision["iteration_result"] == "RETRY"
    assert decision["milestone_result"] == "RETRY"
    assert decision["next_instruction"] == "run shadow deployment"


def test_genuine_external_dependency_can_remain_blocked(tmp_path):
    module = load_agent(tmp_path)
    job = contract_job(module, tmp_path)
    decision = module.milestone_decision(
        job,
        {"verdict": "BLOCKED", "reason": "required hardware is offline"},
        "IMPLEMENTATION=PASS\nDEPLOYMENT=PENDING\n",
    )
    assert decision["iteration_result"] == "BLOCKED"
    assert decision["milestone_result"] == "BLOCKED"


def test_complete_milestone_can_pass_with_independent_verification(tmp_path):
    module = load_agent(tmp_path)
    job = contract_job(module, tmp_path)
    decision = module.milestone_decision(
        job,
        {"verdict": "PASS", "reason": "independently verified"},
        "IMPLEMENTATION=PASS\nDEPLOYMENT=PASS\nINDEPENDENT_VERIFICATION=PASS\n",
    )
    assert decision == {
        "iteration_result": "PASS",
        "milestone_result": "PASS",
        "reason": "independently verified",
        "next_instruction": "",
    }


def test_missing_independent_verification_field_prevents_pass(tmp_path):
    module = load_agent(tmp_path)
    job = contract_job(module, tmp_path)
    decision = module.milestone_decision(
        job,
        {"verdict": "PASS"},
        "IMPLEMENTATION=PASS\nDEPLOYMENT=PASS\n",
    )
    assert decision["milestone_result"] == "RETRY"
    assert "INDEPENDENT_VERIFICATION" in decision["reason"]


def test_all_equivalent_incomplete_states_are_rejected(tmp_path):
    module = load_agent(tmp_path)
    for state in module.INCOMPLETE_CONTRACT_STATES:
        decision = module.milestone_decision(
            {"mandatory_final_fields": ["GATE"]},
            {"verdict": "PASS"},
            f"GATE={state}\n",
        )
        assert decision["milestone_result"] == "RETRY", state
