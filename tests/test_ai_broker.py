import importlib.util
import pathlib

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lifeos_ai_broker", ROOT / "governor" / "ai_broker.py")
BROKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROKER)


def secret_file(tmp_path, names):
    path = tmp_path / "provider-secrets.env"
    path.write_text("\n".join(f"{name}=test-value" for name in names) + "\n")
    path.chmod(0o600)
    return path


def test_normal_inference_uses_direct_cloud_not_local(monkeypatch, tmp_path):
    monkeypatch.setattr(BROKER, "SECRETS_PATH", secret_file(tmp_path, {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}))
    eligible, _ = BROKER.candidates(privacy="normal", task_class="normal")
    assert eligible
    assert eligible[0]["id"] == "gemini"
    assert all(p["adapter"] == "direct-cloud" for p in eligible)
    assert "ollama" not in {p["id"] for p in eligible}


def test_local_only_can_only_obtain_local_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(BROKER, "SECRETS_PATH", secret_file(tmp_path, {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}))
    eligible, considered = BROKER.candidates(privacy="local-only", task_class="normal")
    assert [p["id"] for p in eligible] == ["ollama"]
    cloud = {"gemini", "groq", "openrouter", "cloudflare", "codex"}
    assert all(item["status"] == "PRIVACY_FORBIDDEN" for item in considered if item["provider"] in cloud)


def test_local_failure_never_falls_back_to_cloud(monkeypatch):
    local = {"id": "ollama", "api_model": "qwen2.5-coder:7b-instruct"}
    monkeypatch.setattr(BROKER, "candidates", lambda **_: ([local], []))
    monkeypatch.setattr(BROKER, "_strict_env", lambda _: {})
    called = []

    def fail(provider, prompt, secrets):
        called.append(provider["id"])
        raise BROKER.BrokerError("local unavailable")

    monkeypatch.setattr(BROKER, "_invoke", fail)
    with pytest.raises(BROKER.BrokerError, match="eligible providers exhausted"):
        BROKER.generate("private task", privacy="local-only")
    assert called == ["ollama"]


def test_forced_cloud_provider_must_still_be_policy_eligible(monkeypatch, tmp_path):
    monkeypatch.setattr(BROKER, "SECRETS_PATH", secret_file(tmp_path, {"GEMINI_API_KEY"}))
    with pytest.raises(BROKER.BrokerError, match="no eligible inference provider"):
        BROKER.generate("private task", privacy="local-only", force_provider="gemini")


def test_tool_chat_passes_openai_schema_through_gemini_compatibility(monkeypatch):
    provider = {"id": "gemini", "api_model": "gemini-3.6-flash"}
    monkeypatch.setattr(BROKER, "candidates", lambda **_: ([provider], []))
    monkeypatch.setattr(BROKER, "_strict_env", lambda _: {"GEMINI_API_KEY": "test"})
    captured = {}

    def fake_post(url, payload, headers=None, timeout=120):
        captured.update(url=url, payload=payload, headers=headers)
        return {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call123", "type": "function", "function": {"name": "write_file", "arguments": '{\"path\":\"x\"}'}}]}}]}

    monkeypatch.setattr(BROKER, "_post_json", fake_post)
    messages = [{"role": "user", "content": "create x"}]
    tools = [{"type": "function", "function": {"name": "write_file", "description": "write", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}]
    result = BROKER.chat(messages, tools=tools, tool_choice="auto")
    assert captured["url"].endswith("/v1beta/openai/chat/completions")
    assert captured["payload"]["messages"] is messages
    assert captured["payload"]["tools"] is tools
    assert captured["payload"]["tool_choice"] == "auto"
    assert captured["headers"]["Authorization"] == "Bearer test"
    assert result["finish_reason"] == "tool_calls"
    assert result["message"]["tool_calls"][0]["function"]["name"] == "write_file"


def test_tool_chat_private_fails_closed():
    with pytest.raises(BROKER.BrokerError, match="private inference"):
        BROKER.chat(
            [{"role": "user", "content": "private task"}],
            tools=[{"type": "function", "function": {"name": "x", "parameters": {"type": "object"}}}],
            privacy="local-only",
        )
