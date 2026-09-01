import json, pathlib, stat, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engineer"))
from cleanup_audit import classify
from provider_router import PolicyError, load_policy, load_secret_names, route
from review_packet import build

def policy(): return load_policy(ROOT / "governor/policy.json")

def test_missing_credentials_are_reported_and_next_free_provider_selected():
    result = route(policy(), "normal", {"GROQ_API_KEY"})
    assert result["selected_provider"] == "groq"
    assert result["considered"][0] == {"provider": "gemini", "status": "CREDENTIAL_REQUIRED"}
    assert result["max_attempts"] == 2

def test_cooldown_routes_without_retry_storm():
    result = route(policy(), "normal", {"GEMINI_API_KEY", "GROQ_API_KEY"}, {"gemini": 101}, now=100)
    assert result["selected_provider"] == "groq"
    assert result["considered"][0]["status"] == "COOLDOWN"

def test_roles_keep_ollama_tiny_and_codex_review_only():
    assert route(policy(), "tiny", set())["selected_provider"] == "ollama"
    assert route(policy(), "review", set())["selected_provider"] == "codex"
    assert route(policy(), "normal", set())["fail_closed"] is True

def test_secret_file_requires_exact_0600_and_never_returns_values(tmp_path):
    secret = tmp_path / "providers.env"; secret.write_text("GEMINI_API_KEY=do-not-log\n"); secret.chmod(0o644)
    try: load_secret_names(secret); assert False
    except PolicyError: pass
    secret.chmod(0o600)
    assert load_secret_names(secret) == {"GEMINI_API_KEY"}

def test_cleanup_is_dry_run_and_never_classifies_safe_to_remove(tmp_path):
    (tmp_path / ".openhands").mkdir(); (tmp_path / ".openhands.backup").mkdir()
    result = classify(tmp_path)
    assert result["automatic_deletion"] == "DISABLED" and result["safe_to_remove"] == []
    assert any(x["classification"] == "REVIEW_REQUIRED" for x in result["items"])

def test_policy_is_valid_json_and_zero_spend():
    item = json.loads((ROOT / "governor/policy.json").read_text())
    assert item["routing"]["allow_paid_fallback"] is False

def test_review_packet_is_compact_metadata_not_repository_content():
    result = build(ROOT)
    assert result["provider_role"] == "codex-senior-review"
    assert result["content_included"] is False
    assert len(json.dumps(result)) < 16000
