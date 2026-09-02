import importlib.machinery


def test_queue_exposes_durable_hierarchy_progress():
    module = importlib.machinery.SourceFileLoader("ha_plan_progress", "governor/ha_issue_queue_bridge.py").load_module()
    durable = {"issues": {"27": {"plan": {"state": "IN_PROGRESS", "milestones": [
        {"id": "m1", "targets": [
            {"id": "t1", "state": "PASS", "depends_on": [], "evidence": []},
            {"id": "t2", "state": "BLOCKED", "depends_on": ["t1"],
             "evidence": [{"summary": "dependency unavailable"}]},
            {"id": "t3", "state": "PLANNED", "depends_on": ["t1"], "evidence": []},
        ]}]}}}}
    result = module.issue_plan_progress(27, durable)
    assert result["completed_targets"] == 1
    assert result["total_targets"] == 3
    assert result["current_milestone"] == "m1"
    assert result["current_target"] == "t3"  # independent work remains eligible
    assert result["blocker"] == "dependency unavailable"
