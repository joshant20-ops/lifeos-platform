import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "governor" / "scripts" / "openhands-task-ledger.py"
spec = importlib.util.spec_from_file_location("task_ledger", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def test_assess_returns_earliest_unmet_solution_neutral_objective():
    snapshot = {name: False for name, _ in module.OBJECTIVES}
    snapshot["task_understood"] = True
    snapshot["implementation_inspected"] = True
    result = module.assess(snapshot)

    assert result["complete"] is False
    assert result["earliest_unmet"]["name"] == "defect_established"
    assert "how" not in module.recovery_message(result).lower()


def test_repeated_actions_trigger_stall_recovery():
    result = module.assess({"repeated_action_count": 3})
    message = module.recovery_message(result)

    assert result["stalled"] is True
    assert "no objective advanced" in message
    assert "Earliest unmet objective" in message


def test_complete_ledger_requests_final_check():
    snapshot = {name: True for name, _ in module.OBJECTIVES}
    result = module.assess(snapshot)

    assert result["complete"] is True
    assert result["earliest_unmet"] is None
    assert "final completeness check" in module.recovery_message(result)
