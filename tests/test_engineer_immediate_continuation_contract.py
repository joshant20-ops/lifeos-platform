from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = (ROOT / "governor" / "autonomous_agent.py").read_text()
POLICY = (ROOT / "docs" / "architecture" / "engineer-self-improvement.md").read_text().lower()


def test_agent_has_bounded_immediate_continuation_support():
    for token in (
        "CONTINUATION_MAX_DEPTH",
        "continuation_parent",
        "continuation_depth",
        "spawn_continuation",
        "continuation_allowed",
    ):
        assert token in AGENT


def test_continuation_is_event_driven_not_hourly_polling():
    assert "threading.Thread" in AGENT
    assert "spawn_continuation" in AGENT
    assert "hourly" not in AGENT.lower()


def test_continuation_stops_on_terminal_or_safety_conditions():
    for token in (
        "PASS",
        "BLOCKED",
        "repeated deterministic failure",
        "CONTINUATION_MAX_DEPTH",
    ):
        assert token in AGENT


def test_continuation_is_explicitly_opt_in_and_auditable():
    for token in (
        "continuation_enabled",
        "continuation_reason",
        "continuation_parent",
        "continuation_depth",
    ):
        assert token in AGENT


def test_protected_boundary_remains_external():
    for term in (
        "root broker",
        "allow-list",
        "verifier",
        "job publisher",
        "job runner",
    ):
        assert term in POLICY
    assert "must not self-modify" in POLICY
