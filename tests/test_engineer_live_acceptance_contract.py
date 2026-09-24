import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT = (ROOT / "governor/autonomous_agent.py").read_text()


def test_health_exposes_openhands_owner_and_retired_governor_continuation():
    health = AGENT[AGENT.index('if path == "/health":'):AGENT.index('if path == "/context":')]
    assert '"engineering_session_owner": "openhands"' in health
    assert '"governor_continuation": "retired"' in health


def test_jobs_endpoint_is_not_silently_capped_to_recent_history():
    listing = AGENT[AGENT.index("def list_jobs("):AGENT.index("def set_stage(")]
    assert "def list_jobs(limit=None):" in listing
    assert "if limit is not None:" in listing
