import importlib.machinery
import json
from pathlib import Path


def load(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_BACKLOG_STATE", str(tmp_path))
    return importlib.machinery.SourceFileLoader("backlog_runner_test", "governor/backlog_runner.py").load_module()


def issue(number, priority=1, labels=()):
    return {"number": number, "title": f"P{priority} Issue {number}", "created_at": "2026-01-01", "labels": [{"name": x} for x in labels]}


def test_blocked_cooldown_persists_retry_and_next_issue_selected(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    state = m.empty_state()
    record = m.terminal_record(
        {"status": "BLOCKED", "iterations": [{"evidence": "LIFEOS_WORK_STATE=WAITING_DEPENDENCY\nISSUE_VALIDITY=VALID\nBARRIER=package unavailable\nNEXT_AUTONOMOUS_ACTION=check package\nTESTS=unit pass"}]},
        {"issue": 1, "job_id": "job-one", "started": 100}, {}, timestamp=1000)
    assert record["retry_after"] >= 1000 + 86400
    assert record["retry_count"] == 1
    state["issues"]["1"] = record
    m.save_state(state)
    restarted = m.load_state()
    assert restarted["issues"]["1"]["retry_count"] == 1
    assert m.choose_issue([issue(1, 0), issue(2, 2)], restarted, timestamp=1001)["number"] == 2
    assert m.choose_issue([issue(1, 0)], restarted, timestamp=record["retry_after"])["number"] == 1


def test_issue_6_migration_prevents_ten_minute_redispatch(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    state = m.empty_state(); m.migrate_issue_6(state, timestamp=10_000)
    assert state["issues"]["6"]["retry_count"] == 6
    assert state["issues"]["6"]["retry_after"] >= 96_400
    assert m.choose_issue([issue(6, 0), issue(8, 3)], state, timestamp=10_600)["number"] == 8


def test_completed_not_requeued_and_priority_recomputed(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch); state = m.empty_state()
    state["issues"]["1"] = {"work_state": "PASS", "retry_count": 0, "retry_after": None}
    assert m.choose_issue([issue(1, 0), issue(3, 3), issue(2, 1)], state, timestamp=1)["number"] == 2


def test_single_flight_main_does_not_submit_with_active_governor_job(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch); monkeypatch.setattr(m, "get_open_issues", lambda: [issue(2)])
    monkeypatch.setattr(m, "active_governor_jobs", lambda: [{"id": "existing"}])
    monkeypatch.setattr(m, "submit_issue", lambda *_: (_ for _ in ()).throw(AssertionError("duplicate")))
    assert m.main() == 0


def test_terminal_checkpoint_contains_contract_and_discovery_deduplicates(tmp_path, monkeypatch):
    m = load(tmp_path, monkeypatch)
    record = m.terminal_record({"status": "PASS", "iterations": [{"evidence": "LIFEOS_WORK_STATE=PASS\nISSUE_VALIDITY=VALID\nBARRIER=none\nNEXT_AUTONOMOUS_ACTION=none\nTESTS=12 passed\nCANONICAL_COMMIT=abc"}]}, {"issue": 9, "job_id": "j9", "started": 5}, {}, timestamp=8)
    assert record["tests"] == "12 passed" and record["commits"] == "abc" and record["retry_after"] is None
    raw = __import__("base64").b64encode(json.dumps([{"title": " Same   defect ", "body": "x"}]).encode()).decode()
    monkeypatch.setattr(m, "gh", lambda *a, **k: (_ for _ in ()).throw(AssertionError("duplicate create")))
    assert m.add_discovered_issues("DISCOVERED_ISSUES_JSON_B64=" + raw, 9, [{"number": 11, "title": "same defect"}]) == ["#11 (existing)"]


def test_installer_uses_canonical_source_and_daily_ots_is_preserved():
    installer = Path("governor/scripts/install-backlog-runner-pi5.sh").read_text()
    assert 'install -m 0755 "$REPO/governor/backlog_runner.py" "$WORKER"' in installer
    docs = Path("docs/architecture/OTS_MIGRATION.md").read_text() + Path("docs/architecture/ots-engineer-orchestration.md").read_text()
    assert "daily" in docs.lower() and "OTS" in docs
