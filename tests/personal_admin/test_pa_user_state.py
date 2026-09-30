import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from governor import pa_user_state as user_state


def task(status="OPEN", task_id="renewal-abc123"):
    return {
        "id": task_id,
        "title": "Synthetic renewal",
        "status": status,
        "due_date": "2026-10-15",
        "severity": "normal",
        "source": "gmail",
        "source_message_ids": ["<source@example.test>"],
        "observed_at": 1790790000,
    }


def test_user_comment_is_separate_from_source_evidence_and_verified(tmp_path):
    path = tmp_path / "user_state.json"
    user_state.mutate_action("renewal-abc123", "comment", note="Call insurer", path=path, now=100)
    state = user_state.read_user_state(path)
    payload = user_state.apply_user_state(
        {"schema": "lifeos_tasks_v3", "generated_time": 200, "tasks": [task()], "resolved": []},
        state,
    )
    row = payload["tasks"][0]
    assert row["user_comments"] == [{
        "id": row["user_comments"][0]["id"],
        "created_at": 100,
        "author": "user",
        "source": "user_comment",
        "text": "Call insurer",
    }]
    assert row["source"] == "gmail"
    assert row["source_message_ids"] == ["<source@example.test>"]
    assert payload["user_state_revision"] == 1


def test_explicit_close_survives_machine_replay_and_reopen_is_explicit(tmp_path):
    path = tmp_path / "user_state.json"
    user_state.mutate_action("renewal-abc123", "close", path=path, now=100)
    replay = {"schema": "lifeos_tasks_v3", "generated_time": 200, "tasks": [task("OPEN")], "resolved": []}
    assert user_state.apply_user_state(replay, user_state.read_user_state(path))["resolved"][0]["status"] == "DONE"
    replay_done = {"schema": "lifeos_tasks_v3", "generated_time": 300, "tasks": [task("DONE")], "resolved": []}
    assert user_state.apply_user_state(replay_done, user_state.read_user_state(path))["resolved"][0]["status"] == "DONE"
    user_state.mutate_action("renewal-abc123", "reopen", path=path, now=400)
    assert user_state.apply_user_state(replay_done, user_state.read_user_state(path))["tasks"][0]["status"] == "OPEN"


def test_snooze_and_severity_due_date_override_project_existing_attention(tmp_path):
    path = tmp_path / "user_state.json"
    user_state.mutate_action("renewal-abc123", "snooze", until="2026-10-20", path=path, now=100)
    user_state.mutate_action("renewal-abc123", "severity", severity="high", path=path, now=101)
    user_state.mutate_action("renewal-abc123", "due_date", due_date="2026-10-10", path=path, now=102)
    payload = {"schema": "lifeos_tasks_v3", "generated_time": 1790790000, "tasks": [task()], "resolved": []}
    view = user_state.apply_user_state(payload, user_state.read_user_state(path))
    row = view["tasks"][0]
    assert row["snoozed_until"] == "2026-10-20"
    assert row["severity"] == "high"
    assert row["due_date"] == "2026-10-10"
    assert view["attention"]["counts"]["snoozed"] == 1
    assert view["attention"]["counts"]["needs_me"] == 0
    assert view["briefing"]["confidence"] == "structured_state_only"


def test_dismissed_is_resolved_but_not_completed(tmp_path):
    path = tmp_path / "user_state.json"
    user_state.mutate_action("renewal-abc123", "dismiss", path=path)
    view = user_state.apply_user_state(
        {"schema": "lifeos_tasks_v3", "generated_time": 1790790000, "tasks": [task()], "resolved": []},
        user_state.read_user_state(path),
    )
    assert view["resolved"][0]["status"] == "DISMISSED"
    assert view["attention"]["counts"]["recently_completed"] == 0


def test_invalid_actions_and_dates_are_rejected_without_corrupting_state(tmp_path):
    path = tmp_path / "user_state.json"
    for action, kwargs in [
        ("run_shell", {}),
        ("snooze", {"until": "tomorrow"}),
        ("severity", {"severity": "critical"}),
        ("due_date", {"due_date": "10/10/2026"}),
    ]:
        try:
            user_state.mutate_action("renewal-abc123", action, path=path, **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid action accepted")
    assert user_state.read_user_state(path)["revision"] == 0
