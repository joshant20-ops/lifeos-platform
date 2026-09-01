import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "governor" / "backlog_runner.py"


def load_backlog():
    spec = importlib.util.spec_from_file_location("lifeos_backlog_priority_test", BACKLOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def issue(number, title, labels=(), created="2026-09-01T00:00:00Z"):
    return {
        "number": number,
        "title": title,
        "created_at": created,
        "labels": [{"name": name} for name in labels],
    }


def test_manual_high_priority_beats_normal_p0():
    backlog = load_backlog()
    normal = issue(1, "P0 normal")
    manual = issue(2, "P5 manually raised", ["lifeos-high-priority"])
    assert backlog.priority(manual) < backlog.priority(normal)


def test_multiple_manual_issues_keep_normal_ranking_within_pool():
    backlog = load_backlog()
    p3 = issue(3, "P3 manual", ["lifeos-high-priority"])
    p1 = issue(4, "P1 manual", ["lifeos-high-priority"])
    assert backlog.priority(p1) < backlog.priority(p3)


def test_unchecked_issues_keep_existing_priority_semantics():
    backlog = load_backlog()
    p0 = issue(5, "P0 first")
    p2 = issue(6, "P2 later")
    assert backlog.priority(p0) < backlog.priority(p2)


def test_manual_override_does_not_bypass_eligibility_barriers():
    backlog = load_backlog()
    candidate = issue(7, "P4 blocked manual", ["lifeos-high-priority", "blocked"])
    state = {"issues": {}}
    assert backlog.eligible(candidate, state, timestamp=1_000_000) is False
