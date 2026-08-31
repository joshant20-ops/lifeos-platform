from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "governor" / "engineer_backend.py").read_text()
AGENT = (ROOT / "governor" / "autonomous_agent.py").read_text()


def test_chat_does_not_emit_hidden_transport_markers():
    assert "<!--LIFEOS_PROPOSAL:" not in BACKEND
    assert "<!--LIFEOS_JOB:" not in BACKEND
    assert "Proposal ref:" in BACKEND


def test_proposal_is_server_side_and_command_plans_are_rejected():
    assert "PROPOSALS = {}" in BACKEND
    assert "normalise_proposal" in BACKEND
    assert "lifeos-autonomous-agent --" in BACKEND
    assert "Never invent CLI commands" in BACKEND


def test_natural_status_intents_are_supported():
    for phrase in ("eta", "how long", "what is it doing", "is it stuck", "progress report"):
        assert phrase in BACKEND
    assert "history_durations" in BACKEND
    assert "evidence_summary" in BACKEND


def test_engineer_receives_read_only_runtime_context():
    assert 'AGENT_URL + "/context"' in BACKEND
    assert "LOCAL READ-ONLY CONTEXT" in BACKEND
    assert 'path == "/context"' in AGENT
    assert "repo_context" in AGENT


def test_agent_records_stage_telemetry():
    for stage in ("builder", "publication", "runtime", "verifier", "retry_planning"):
        assert f'"{stage}"' in AGENT
    assert "stage_changed_at" in AGENT


def test_repeated_deterministic_failure_is_bounded():
    assert "REPEATED_FAILURE_LIMIT" in AGENT
    assert "failure_signature" in AGENT
    assert "REPLAN REQUIRED" in AGENT
    assert "repeated deterministic failure detected" in AGENT
