import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = (ROOT / "governor/autonomous_agent_server.py").read_text(encoding="utf-8")
BUILDER = (ROOT / "governor/scripts/lifeos-cloud-builder").read_text(encoding="utf-8")


def test_cloud_builder_uses_codex_only_for_sanitized_engineering():
    assert 'AGENTS+=("codex|codex|")' in BUILDER
    assert 'AGENTS+=("governor-broker|openhands|' not in BUILDER
    assert 'cloud_builder_forbidden_for_local_only_job' in BUILDER


def test_server_honors_only_explicit_engineering_model_capability():
    assert 'trusted_engineering = requested_model.startswith("openai/lifeos-engineering-")' in SERVER
    assert 'if trusted_engineering and requested_privacy == "normal":' in SERVER
    assert 'privacy = "local-only" if detected == "local-only" else requested_privacy' in SERVER
