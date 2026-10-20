import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "governor" / "pa_duplicate_audit.py"


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.read_bytes()


def test_audit_emits_aggregate_counts_only_and_does_not_mutate_inputs(tmp_path):
    private_title = "PRIVATE CLAIM TITLE"
    task_path = tmp_path / "tasks.json"
    user_path = tmp_path / "user_state.json"
    task_bytes = write_json(task_path, {
        "schema": "lifeos_tasks_v3",
        "tasks": [
            {
                "id": "private-task-a",
                "title": private_title,
                "counterparty": "Acme Ltd",
                "topic": "Claim renewal",
                "case_reference_ids": ["UK-HB-12345"],
                "source_message_ids": ["<private-message@example.test>"],
            },
            {
                "id": "private-task-b",
                "title": "Another private title",
                "counterparty": "Acme Ltd",
                "topic": "Claim renewal",
                "case_reference_ids": ["UKHB12345"],
                "timeline_events": [{"message_id": "<private-message@example.test>"}],
            },
            {
                "id": "separate-task",
                "title": "Do not print this either",
                "counterparty": "Different",
                "topic": "Other matter",
            },
        ],
        "resolved": [],
    })
    user_bytes = write_json(user_path, {
        "schema": "lifeos_pa_user_state_v1",
        "revision": 3,
        "obligations": {
            "private-task-a": {
                "status_override": "DONE",
                "comments": [{"text": "PRIVATE USER COMMENT"}],
            },
            "private-task-b": {
                "status_override": "OPEN",
            },
            "orphan-task": {"severity_override": "high"},
        },
    })

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--task-state", str(task_path),
         "--user-state", str(user_path)],
        check=False, capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == 0
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert fields["PA_DUPLICATE_AUDIT_RESULT"] == "PASS"
    assert fields["PA_DUPLICATE_AUDIT_TASKS"] == "3"
    assert fields["PA_DUPLICATE_AUDIT_CANDIDATE_PAIRS"] == "1"
    assert fields["PA_DUPLICATE_AUDIT_SHARED_SOURCE_PAIRS"] == "1"
    assert fields["PA_DUPLICATE_AUDIT_CASE_REFERENCE_PAIRS"] == "1"
    assert fields["PA_DUPLICATE_AUDIT_COUNTERPARTY_TOPIC_PAIRS"] == "1"
    assert fields["PA_DUPLICATE_AUDIT_CANDIDATE_PAIRS_WITH_USER_STATE"] == "1"
    assert fields["PA_DUPLICATE_AUDIT_CANDIDATE_PAIRS_WITH_OVERRIDE_CONFLICTS"] == "1"
    assert fields["PA_DUPLICATE_AUDIT_ORPHAN_USER_STATE_ENTRIES"] == "1"
    assert fields["PA_DUPLICATE_AUDIT_READ_ONLY"] == "YES"
    assert private_title not in result.stdout + result.stderr
    assert "private-task" not in result.stdout + result.stderr
    assert "private-message" not in result.stdout + result.stderr
    assert "PRIVATE USER COMMENT" not in result.stdout + result.stderr
    assert task_path.read_bytes() == task_bytes
    assert user_path.read_bytes() == user_bytes


def test_missing_optional_user_state_is_read_as_empty(tmp_path):
    task_path = tmp_path / "tasks.json"
    write_json(task_path, {"schema": "lifeos_tasks_v3", "tasks": [], "resolved": []})
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--task-state", str(task_path),
         "--user-state", str(tmp_path / "missing.json")],
        check=False, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "PA_DUPLICATE_AUDIT_RESULT=PASS" in result.stdout
    assert "PA_DUPLICATE_AUDIT_TASKS=0" in result.stdout


def test_invalid_schema_fails_with_fixed_error_and_no_input_content(tmp_path):
    private_value = "PRIVATE TASK BODY"
    task_path = tmp_path / "tasks.json"
    task_path.write_text(json.dumps({"schema": "wrong", "title": private_value}))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--task-state", str(task_path),
         "--user-state", str(tmp_path / "missing.json")],
        check=False, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "PA_DUPLICATE_AUDIT_ERROR=INPUT_SCHEMA_INVALID" in result.stdout
    assert private_value not in result.stdout + result.stderr


def test_symlink_input_fails_closed_without_disclosing_path(tmp_path):
    target = tmp_path / "real.json"
    target.write_text(json.dumps({"schema": "lifeos_tasks_v3", "tasks": [], "resolved": []}))
    link = tmp_path / "linked.json"
    link.symlink_to(target)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--task-state", str(link),
         "--user-state", str(tmp_path / "missing.json")],
        check=False, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "PA_DUPLICATE_AUDIT_ERROR=INPUT_UNREADABLE" in result.stdout
    assert str(tmp_path) not in result.stdout + result.stderr
