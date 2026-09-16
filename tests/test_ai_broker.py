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


def test_normal_inference_uses_local_stable_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        BROKER,
        "SECRETS_PATH",
        secret_file(tmp_path, {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}),
    )
    eligible, _ = BROKER.candidates(privacy="normal", task_class="normal")
    assert eligible
    assert [p["id"] for p in eligible] == ["ollama"]
    assert eligible[0]["adapter"] == "local-builder"
    assert "codex" not in {p["id"] for p in eligible}


def test_local_only_can_only_obtain_local_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(
        BROKER,
        "SECRETS_PATH",
        secret_file(tmp_path, {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}),
    )
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


def test_local_inference_acquires_and_releases_tower_lease(monkeypatch):
    events = []
    monkeypatch.setattr(BROKER, "_publish_lease", lambda state, **_: events.append(state))
    monkeypatch.setattr(BROKER, "_ollama_once", lambda prompt, model: "ok")
    assert BROKER._ollama("hello", "model") == "ok"
    assert events == ["active", "released"]


def test_local_inference_renews_lease_while_waiting_for_wake(monkeypatch):
    events = []
    attempts = iter([BROKER.BrokerError("off"), "ok"])
    monkeypatch.setattr(BROKER, "_publish_lease", lambda state, **_: events.append(state))
    monkeypatch.setattr(BROKER, "_wake_local_ai", lambda: True)
    monkeypatch.setattr(BROKER.time, "sleep", lambda _: None)
    monkeypatch.setattr(BROKER, "_ollama_once", lambda prompt, model: next(attempts))

    original = BROKER._ollama_once
    def invoke(prompt, model):
        value = original(prompt, model)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(BROKER, "_ollama_once", invoke)
    assert BROKER._ollama("hello", "model") == "ok"
    assert events == ["active", "active", "released"]


def test_tool_chat_translates_gemini_function_call(monkeypatch):
    provider = {"id": "gemini", "api_model": "gemini-3.6-flash"}
    monkeypatch.setattr(
        BROKER,
        "_post_json",
        lambda *args, **kwargs: {
            "candidates": [{"content": {"parts": [{"functionCall": {"id": "call123", "name": "write_file", "args": {"path": "x", "content": "y"}}}]}}]
        },
    )
    result = BROKER._gemini_chat(
        [{"role": "user", "content": "create x"}],
        [{"type": "function", "function": {"name": "write_file", "description": "write", "parameters": {"type": "object", "properties": {}}}}],
        provider,
        {"GEMINI_API_KEY": "test"},
    )
    assert result["finish_reason"] == "tool_calls"
    call = result["message"]["tool_calls"][0]
    assert call["id"] == "call123"
    assert call["function"]["name"] == "write_file"
    assert '"path":"x"' in call["function"]["arguments"]


def test_tool_chat_private_fails_closed_without_cloud_fallback(monkeypatch):
    local = {"id": "ollama", "api_model": "qwen2.5-coder:7b-instruct"}
    calls = []

    def candidates(*, privacy, task_class):
        calls.append((privacy, task_class))
        assert privacy == "local-only"
        return [local], []

    monkeypatch.setattr(BROKER, "candidates", candidates)
    monkeypatch.setattr(BROKER, "_strict_env", lambda _: {})
    monkeypatch.setattr(
        BROKER,
        "_ollama_chat",
        lambda *args, **kwargs: (_ for _ in ()).throw(BROKER.BrokerError("local unavailable")),
    )
    with pytest.raises(BROKER.BrokerError, match="tool-capable providers exhausted"):
        BROKER.chat(
            [{"role": "user", "content": "private task"}],
            tools=[{"type": "function", "function": {"name": "x", "parameters": {"type": "object"}}}],
            privacy="local-only",
        )
    assert calls == [("local-only", "normal")]


def test_normal_tool_chat_uses_local_stable_base(monkeypatch):
    local = {"id": "ollama", "api_model": "qwen2.5-coder:7b-instruct"}
    routed = []

    def candidates(*, privacy, task_class):
        assert task_class == "normal"
        return [local], []

    monkeypatch.setattr(BROKER, "candidates", candidates)
    monkeypatch.setattr(BROKER, "_strict_env", lambda _: {})
    monkeypatch.setattr(
        BROKER,
        "_ollama_chat",
        lambda *args, **kwargs: (
            routed.append("ollama")
            or {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ),
    )
    result = BROKER.chat(
        [{"role": "user", "content": "sanitized engineering task"}],
        tools=[{"type": "function", "function": {"name": "x", "parameters": {"type": "object"}}}],
        privacy="normal",
    )
    assert routed == ["ollama"]
    assert result["provider"] == "ollama"
