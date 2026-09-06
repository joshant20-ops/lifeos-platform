from governor import ai_broker


def test_tool_chat_falls_back_from_gemini_to_openrouter(monkeypatch):
    providers = [
        {"id": "gemini", "api_model": "gemini-test"},
        {"id": "openrouter", "api_model": "openrouter/test"},
    ]
    monkeypatch.setattr(ai_broker, "candidates", lambda **_: (providers, []))
    monkeypatch.setattr(ai_broker, "_strict_env", lambda _: {"OPENROUTER_API_KEY": "x"})

    def gemini_fail(*args, **kwargs):
        raise ai_broker.BrokerError("provider HTTP 400")

    monkeypatch.setattr(ai_broker, "_gemini_chat", gemini_fail)
    monkeypatch.setattr(
        ai_broker,
        "_openrouter_chat",
        lambda *args, **kwargs: {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "shell", "arguments": "{}"},
                    }
                ],
            },
            "finish_reason": "tool_calls",
        },
    )

    result = ai_broker.chat(
        [{"role": "user", "content": "inspect"}],
        tools=[{"type": "function", "function": {"name": "shell", "parameters": {"type": "object"}}}],
    )
    assert result["provider"] == "openrouter"
    assert result["finish_reason"] == "tool_calls"
    assert result["message"]["tool_calls"][0]["function"]["name"] == "shell"


def test_private_tool_chat_still_fails_closed():
    try:
        ai_broker.chat([], tools=[], privacy="local-only")
    except ai_broker.BrokerError as exc:
        assert "private inference" in str(exc)
    else:
        raise AssertionError("local-only tool chat must fail closed")
