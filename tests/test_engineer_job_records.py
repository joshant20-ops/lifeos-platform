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


class FakeGit:
    def __init__(self, push_rc=0):
        self.push_rc = push_rc
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        rc, out = 0, ""
        if args[1:4] == ["diff", "--cached", "--quiet"]:
            rc = 1
        elif args[1] == "push":
            rc = self.push_rc
        elif args[1] == "rev-parse":
            out = "deadbeef\n"
        return subprocess.CompletedProcess(args, rc, out, "push rejected" if rc else "")


def test_successful_git_publication(tmp_path):
    fake = FakeGit()
    result = records.publish_record(tmp_path, job(), run=fake)
    assert result == {"state": "PUBLISHED", "commit": "deadbeef"}
    data = json.loads((tmp_path / "governor/job_records/de629fc4ea87.json").read_text())
    assert data["record_publication"]["state"] == "PUBLISHED"


def test_failed_git_publication_is_truthful_and_retryable(tmp_path):
    fake = FakeGit(push_rc=1)
    result = records.publish_record(tmp_path, job(), run=fake)
    assert result["state"] == "UNPUBLISHED"
    data = json.loads((tmp_path / "governor/job_records/de629fc4ea87.json").read_text())
    assert data["record_publication"]["state"] == "UNPUBLISHED"
    assert any(call[1] == "commit" for call in fake.calls)
