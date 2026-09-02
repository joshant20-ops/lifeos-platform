import importlib.machinery
import json

import pytest


def load(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_BACKLOG_STATE", str(tmp_path))
    return importlib.machinery.SourceFileLoader(
        "issue_pickup_contract", "governor/backlog_runner.py"
    ).load_module()


def issue(number, *, labels=(), body="authoritative task body"):
    return {
        "number": number,
        "title": f"P1 Issue {number}",
        "body": body,
        "created_at": "2026-01-01T00:00:00Z",
        "labels": [{"name": label} for label in labels],
    }


def test_eligible_ready_issue_is_submitted_once(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    state = m.empty_state()
    submitted = []
    monkeypatch.setattr(m, "api", lambda *args, **kwargs: submitted.append(args) or {"id": "job-7"})
    monkeypatch.setattr(m, "issue_comment", lambda *_: None)

    m.submit_issue(issue(7, labels=("lifeos-engineer-ready",)), state)

    assert state["active"]["job_id"] == "job-7"
    assert len(submitted) == 1
    assert not m.eligible(issue(7), {"issues": {"7": {"work_state": "PASS"}}})


@pytest.mark.parametrize("label", ["blocked", "waiting-human", "waiting-dependency", "do-not-automate", "lifeos-engineer-ignore"])
def test_ineligible_issue_is_not_selected(tmp_path, monkeypatch, label):
    m = load(tmp_path, monkeypatch)
    assert m.choose_issue([issue(7, labels=(label,))], m.empty_state(), timestamp=1) is None


def test_active_or_consumed_issue_is_not_duplicated(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    state = m.empty_state()
    state["active"] = {"issue": 7, "job_id": "job-7", "phase": "planning"}
    m.save_state(state)
    monkeypatch.setattr(m, "get_open_issues", lambda: [issue(7)])
    monkeypatch.setattr(m, "finish_active", lambda *_: True)
    monkeypatch.setattr(m, "submit_issue", lambda *_: pytest.fail("duplicate submission"))
    assert m.main() == 0


def test_failed_ingestion_is_persisted_and_retryable_after_cooldown(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    state = m.empty_state()
    monkeypatch.setattr(m, "now", lambda: 1_000)
    monkeypatch.setattr(m, "api", lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("private detail")))

    with pytest.raises(ConnectionError):
        m.submit_issue(issue(7), state)

    saved = json.loads(m.STATE.read_text())
    record = saved["issues"]["7"]
    assert record["work_state"] == "WAITING_DEPENDENCY"
    assert record["last_ingestion_failure"] == {"attempted_at": 1_000, "error_type": "ConnectionError"}
    assert "private detail" not in m.STATE.read_text()
    assert not m.eligible(issue(7), saved, timestamp=record["retry_after"] - 1)
    assert m.eligible(issue(7), saved, timestamp=record["retry_after"])


def test_issue_body_is_task_authority_and_obsolete_comments_are_absent(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    state = m.empty_state()
    captured = {}

    def api(_path, _method, payload):
        captured.update(payload)
        return {"id": "job-7"}

    monkeypatch.setattr(m, "api", api)
    monkeypatch.setattr(m, "issue_comment", lambda *_: None)
    candidate = issue(7, body="CURRENT R580 TASK\nProduction change requires human approval")
    candidate["comments"] = [{"body": "OBSOLETE CYCLE_1_RESULT bootstrap diagnostic"}]

    m.submit_issue(candidate, state)

    prompt = captured["request"]
    assert "CURRENT R580 TASK" in prompt
    assert "Production change requires human approval" in prompt
    assert "CYCLE_1_RESULT" not in prompt
