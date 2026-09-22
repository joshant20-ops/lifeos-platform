import importlib.util
import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("job_records", ROOT / "governor" / "job_records.py")
records = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(records)


def job(status="PASS"):
    return {
        "id": "de629fc4ea87", "request": "Continue OTS migration", "privacy": "normal",
        "status": status, "stage": "complete" if status == "PASS" else "blocked",
        "created_at": "2026-09-01T10:00:00+0000", "completed_at": "2026-09-01T10:01:00+0000",
        "iterations": [{"evidence": "RUNTIME_RC=7\n"}],
        "implementation_summary": "Added records", "changed_files": ["b", "a", "a"],
        "canonical_commits": ["abc"], "tests": {"count": 8, "summary": "passed"},
    }


def test_pass_record_is_deterministic_and_complete():
    first = records.serialise_record(records.make_record(job(), "PUBLISHED"))
    second = records.serialise_record(records.make_record(job(), "PUBLISHED"))
    assert first == second
    data = json.loads(first)
    assert data["final_status"] == "PASS"
    assert data["changed_files"] == ["a", "b"]
    assert data["runtime_return_code"] == 7
    assert data["record_publication"]["state"] == "PUBLISHED"


def test_blocked_runtime_and_human_action_record():
    value = job("BLOCKED")
    value.update(blocked_reason="hardware unavailable", failure_class="external", human_action_state="REQUIRED")
    data = records.make_record(value)
    assert data["failure"] == {"class": "external", "reason": "hardware unavailable"}
    assert data["human_action_state"] == "REQUIRED"


def test_sanitisation_patterns_and_raw_data_omission():
    value = job()
    value["implementation_summary"] = "password=hunter2 Authorization:Bearer bearer-value token:xyz https://u:p@example"
    value["environment"] = {"SAFE": "still must not publish"}
    value["failure_reason"] = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    rendered = records.serialise_record(records.make_record(value))
    for secret in ("hunter2", "bearer-value", "xyz", "https://u:p@", "BEGIN PRIVATE KEY", "still must not publish"):
        assert secret not in rendered


def test_runtime_stages_record_outside_git_checkout(tmp_path, monkeypatch):
    state = tmp_path / "state"
    repo = tmp_path / "readonly-source"
    repo.mkdir()
    monkeypatch.setenv("LIFEOS_AGENT_STATE", str(state))

    result = records.publish_record(repo, job())

    staged = state / "job_records/de629fc4ea87.json"
    assert result == {"state": "STAGED", "path": str(staged)}
    data = json.loads(staged.read_text())
    assert data["record_publication"]["state"] == "STAGED"
    assert not (repo / "governor/job_records/de629fc4ea87.json").exists()


def test_runtime_publication_requires_external_state_root(tmp_path, monkeypatch):
    state = tmp_path / "state"
    repo = tmp_path / "readonly-source"
    repo.mkdir()
    monkeypatch.setenv("LIFEOS_AGENT_STATE", str(state))
    result = records.publish_record(repo, job())
    assert result["state"] == "STAGED"
    assert pathlib.Path(result["path"]).is_relative_to(state)
    assert not (repo / "governor/job_records").exists()
