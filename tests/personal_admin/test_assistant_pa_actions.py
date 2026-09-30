import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "governor"))
import pa_user_state as bridge_user_state
import assistant_bridge as bridge


def fixture(path, task_ids=("renewal-abc123",)):
    rows = [
        {
            "id": task_id,
            "title": "Synthetic renewal " + str(index + 1),
            "status": "OPEN",
            "due_date": None,
            "severity": "normal",
            "source": "gmail",
            "source_message_ids": ["<synthetic-%s@example.test>" % index],
            "observed_at": 1790790000,
        }
        for index, task_id in enumerate(task_ids)
    ]
    path.write_text(json.dumps({
        "schema": "lifeos_tasks_v3",
        "generated_time": 1790790000,
        "tasks": rows,
        "resolved": [],
        "attention": {},
        "briefing": {},
    }))
    return rows


def test_conversation_proposes_then_confirms_and_verifies_user_close(tmp_path, monkeypatch):
    tasks = tmp_path / "tasks.json"
    fixture(tasks)
    monkeypatch.setattr(bridge, "PA_TASKS_FILE", tasks)
    monkeypatch.setattr(pa_user_state, "STATE_PATH", tmp_path / "user_state.json")
    proposal = bridge.process_pa_action("close Synthetic renewal 1", "client-a")
    assert proposal["action_status"] == "proposed"
    assert proposal["action_task_id"] == "renewal-abc123"
    assert bridge_user_state.read_user_state()["revision"] == 0
    result = bridge.process_pa_action("confirm renewal-abc123", "client-a")
    assert result["action_status"] == "verified"
    state = pa_user_state.read_user_state()
    assert state["obligations"]["renewal-abc123"]["status_override"] == "DONE"
    replay = {"schema": "lifeos_tasks_v3", "generated_time": 1790790000, "tasks": fixture(tasks), "resolved": []}
    assert bridge_user_state.apply_user_state(replay, state)["resolved"][0]["status"] == "DONE"


def test_ambiguous_conversation_action_requests_identity_without_mutation(tmp_path, monkeypatch):
    tasks = tmp_path / "tasks.json"
    fixture(tasks, ("renewal-one", "renewal-two"))
    monkeypatch.setattr(bridge, "PA_TASKS_FILE", tasks)
    monkeypatch.setattr(pa_user_state, "STATE_PATH", tmp_path / "user_state.json")
    result = bridge.process_pa_action("dismiss renewal", "client-b")
    assert result["needs_clarification"] is True
    assert result["action_status"] == "ambiguous"
    assert pa_user_state.read_user_state()["revision"] == 0


def test_conversational_actions_parse_only_allowlisted_fields():
    assert bridge._parse_pa_action("snooze renewal-abc123 until 2026-10-15") == {
        "action": "snooze", "target": "renewal-abc123", "until": "2026-10-15",
    }
    assert bridge._parse_pa_action('add comment "Call insurer" to renewal-abc123') == {
        "action": "comment", "target": "renewal-abc123", "note": "Call insurer",
    }
    assert bridge._parse_pa_action("set severity of renewal-abc123 to high") == {
        "action": "severity", "target": "renewal-abc123", "severity": "high",
    }
    assert bridge._parse_pa_action("run shell command") is None
