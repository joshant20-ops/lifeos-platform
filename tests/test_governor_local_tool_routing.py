import importlib.util
import json
import pathlib
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "lifeos_ai_broker_local_tool_test", ROOT / "governor" / "ai_broker.py"
)
broker = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(broker)


def test_normal_candidates_include_local_builder_adapter():
    with mock.patch.object(broker.ROUTER, "load_policy", return_value={"providers": []}), \
         mock.patch.object(broker.ROUTER, "load_secret_names", return_value=set()), \
         mock.patch.object(broker.ROUTER, "eligible_providers", return_value=([], [])) as eligible:
        broker.candidates(privacy="normal", task_class="normal")
    assert eligible.call_args.kwargs["available_adapters"] == {"local-builder", "direct-cloud"}


def test_ollama_json_tool_fallback_accepts_only_declared_tools():
    tools = [{"type": "function", "function": {"name": "report_test_value"}}]
    call = broker._ollama_tool_call_from_content(
        json.dumps({"name": "report_test_value", "arguments": {"value": "OK"}}), tools
    )
    assert call["function"]["name"] == "report_test_value"
    assert json.loads(call["function"]["arguments"]) == {"value": "OK"}
    assert broker._ollama_tool_call_from_content(
        json.dumps({"name": "undeclared", "arguments": {}}), tools
    ) is None


def test_chat_dispatches_policy_selected_ollama_tool_provider():
    provider = {"id": "ollama", "api_model": "qwen2.5-coder:7b-instruct"}
    response = {
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_test",
                "type": "function",
                "function": {"name": "x", "arguments": "{}"},
            }],
        },
        "finish_reason": "tool_calls",
    }
    with mock.patch.object(broker, "candidates", return_value=([provider], [])), \
         mock.patch.object(broker, "_strict_env", return_value={}), \
         mock.patch.object(broker, "_ollama_chat", return_value=response) as local:
        result = broker.chat(
            [{"role": "user", "content": "call x"}],
            tools=[{"type": "function", "function": {"name": "x"}}],
        )
    local.assert_called_once()
    assert result["provider"] == "ollama"
    assert result["finish_reason"] == "tool_calls"
