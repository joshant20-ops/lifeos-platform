from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = (ROOT / "governor" / "autonomous_agent.py").read_text()
POLICY = (ROOT / "docs" / "architecture" / "engineer-self-improvement.md").read_text().lower()
REGISTRY = (ROOT / "docs" / "operations" / "migration-redirect-registry.md").read_text()


def test_governor_continuation_strategy_loop_is_retired():
    for token in (
        "def continuation_allowed(",
        "def spawn_continuation(",
        "CONTINUATION_MAX_DEPTH",
        "spawn_continuation(final)",
    ):
        assert token not in AGENT


def test_legacy_continuation_input_fails_closed_with_openhands_redirect():
    for token in (
        "RETIRED_CONTINUATION_FIELDS",
        '"error": "governor_continuation_retired"',
        '"canonical_owner": "openhands"',
        "self.send_json(410",
    ):
        assert token in AGENT


def test_health_reports_canonical_engineering_owner():
    assert '"engineering_session_owner": "openhands"' in AGENT
    assert '"governor_continuation": "retired"' in AGENT


def test_retired_interface_is_registered_for_consumer_migration():
    assert "MIG-002" in REGISTRY
    assert "Governor continuation job fields" in REGISTRY
    assert "OpenHands engineering session" in REGISTRY


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
