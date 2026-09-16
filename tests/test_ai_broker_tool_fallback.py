import pytest

from governor import ai_broker


def test_normal_tool_chat_has_no_disabled_cloud_or_private_local_fallback(monkeypatch):
    called = []
    monkeypatch.setattr(ai_broker, "candidates", lambda **_: ([], []))
    monkeypatch.setattr(ai_broker, "_ollama_chat", lambda *a, **k: called.append("ollama"))

    with pytest.raises(ai_broker.BrokerError, match="no eligible tool-capable provider"):
        ai_broker.chat(
            [{"role": "user", "content": "sanitized engineering"}],
            tools=[{"type": "function", "function": {"name": "shell", "parameters": {"type": "object"}}}],
            privacy="normal",
        )
    assert called == []


def test_private_tool_chat_fails_closed_when_local_provider_fails(monkeypatch):
    local = {"id": "ollama", "api_model": "qwen2.5-coder:7b-instruct"}
    monkeypatch.setattr(ai_broker, "candidates", lambda **_: ([local], []))
    monkeypatch.setattr(
        ai_broker,
        "_ollama_chat",
        lambda *a, **k: (_ for _ in ()).throw(ai_broker.BrokerError("local unavailable")),
    )

    with pytest.raises(ai_broker.BrokerError, match="tool-capable providers exhausted: ollama"):
        ai_broker.chat([], tools=[], privacy="local-only")
