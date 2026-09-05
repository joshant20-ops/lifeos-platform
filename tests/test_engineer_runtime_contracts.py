import pathlib


BACKEND = pathlib.Path("governor/engineer_backend.py")


def test_health_is_liveness_and_ready_is_dependency_readiness():
    text = BACKEND.read_text()
    assert 'if path in ("/health", "/v1/health"):' in text
    assert '"status": "ok", "readiness": "/ready"' in text
    assert 'if path in ("/ready", "/v1/ready"):' in text
    health_block = text[text.index('if path in ("/health", "/v1/health"):'):text.index('if path in ("/ready", "/v1/ready"):')]
    assert 'OLLAMA_URL' not in health_block
    assert 'AGENT_URL' not in health_block
    ready_block = text[text.index('if path in ("/ready", "/v1/ready"):'):text.index('if path == "/v1/models":')]
    assert 'AGENT_URL + "/health"' in ready_block
    assert '/api/tags' in ready_block
    assert 'self.send_json(503' in ready_block


def test_system_prompt_forbids_job_proposals_for_information_only_requests():
    text = BACKEND.read_text()
    assert 'Information-only questions must be answered directly' in text
    assert 'ready_to_run must be false' in text
    assert 'Only set ready_to_run true when the user is asking for a change' in text


def test_activation_uses_fresh_job_and_checks_ready_separately():
    text = pathlib.Path('scripts/activate-current-engineer-runtime-v4.sh').read_text()
    assert 'engineer-current-20260905-v4' in text
    assert 'http://127.0.0.1:8793/health' in text
    assert 'http://127.0.0.1:8793/ready' in text
    assert 'METADATA_REPAIR=' not in text
    assert 'Proposal ref' in text
    assert '391' in text
    assert 'NEXT_REQUIRED=phase1_closure_review' in text
