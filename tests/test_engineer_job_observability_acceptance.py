from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "governor" / "engineer_backend.py").read_text()
AGENT = (ROOT / "governor" / "autonomous_agent.py").read_text()


def test_engineer_supports_full_job_history_intent():
    for phrase in (
        "historical jobs",
        "all jobs",
        "job history",
    ):
        assert phrase in BACKEND
    assert "jobs_history_reply" in BACKEND
    assert 'AGENT_URL + "/jobs"' in BACKEND


def test_engineer_supports_queue_summary_intent():
    for phrase in (
        "what jobs are currently running",
        "what is queued",
        "queue status",
    ):
        assert phrase in BACKEND
    assert "jobs_queue_reply" in BACKEND


def test_stuck_detection_is_backed_by_agent_data_not_llm_claims():
    assert "stuck_jobs" in AGENT
    assert "stuck_reason" in AGENT
    assert "stage_changed_at" in AGENT
    assert "STUCK_JOB_MULTIPLIER" in AGENT
    assert 'path == "/jobs/stuck"' in AGENT
    assert "jobs_stuck_reply" in BACKEND
    assert 'AGENT_URL + "/jobs/stuck"' in BACKEND


def test_history_reply_has_operational_fields():
    for field in (
        "id",
        "status",
        "stage",
        "created_at",
        "started_at",
        "completed_at",
        "request",
    ):
        assert field in BACKEND


def test_self_improvement_keeps_security_boundary_external():
    protected_terms = (
        "root broker",
        "allow-list",
        "verifier",
        "job publisher",
        "job runner",
    )
    policy = (ROOT / "docs" / "architecture" / "engineer-self-improvement.md").read_text().lower()
    for term in protected_terms:
        assert term in policy
    assert "must not self-modify" in policy
