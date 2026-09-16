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


def test_runtime_acceptance_probes_use_explicit_private_local_policy():
    deploy = (ROOT / "governor" / "scripts" / "deploy-autonomous-agent-pi5.sh").read_text()
    smoke = (ROOT / ".github" / "workflows" / "lifeos-openhands-action-smoke.yml").read_text()
    for probe in (deploy, smoke):
        assert "lifeos_provider') == 'ollama'" in probe or "j['lifeos_provider']=='ollama'" in probe
        assert "lifeos-local-only-normal" in probe
        assert "lifeos_privacy') == 'local-only'" in probe or "j['lifeos_privacy']=='local-only'" in probe


def test_broker_candidates_expose_only_local_adapter_but_privacy_policy_decides_eligibility():
    with mock.patch.object(broker.ROUTER, "load_policy", return_value={"providers": []}), \
         mock.patch.object(broker.ROUTER, "load_secret_names", return_value=set()), \
         mock.patch.object(broker.ROUTER, "eligible_providers", return_value=([], [])) as eligible:
        broker.candidates(privacy="normal", task_class="normal")
    assert eligible.call_args.kwargs["available_adapters"] == {"local-builder"}


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



def test_ollama_fenced_json_tool_fallback_is_normalized():
    tools = [{"type": "function", "function": {"name": "invoke_skill"}}]
    content = '```json\n{"name":"invoke_skill","arguments":{"name":"bash-runner"}}\n```'
    call = broker._ollama_tool_call_from_content(content, tools)
    assert call is not None
    assert call["function"]["name"] == "invoke_skill"
    assert json.loads(call["function"]["arguments"]) == {"name": "bash-runner"}

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


def test_local_only_tool_chat_uses_ollama_without_cloud_candidates():
    provider = {"id": "ollama", "api_model": "qwen2.5-coder:7b-instruct"}
    response = {
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_local",
                "type": "function",
                "function": {"name": "shell", "arguments": "{\\\"command\\\":\\\"true\\\"}"},
            }],
        },
        "finish_reason": "tool_calls",
    }

    def candidate_set(*, privacy, task_class):
        assert task_class == "substantial"
        if privacy == "local-only":
            return [provider], [{"provider": "ollama", "status": "AVAILABLE"}]
        raise AssertionError("local-only tool routing evaluated cloud candidates")

    with mock.patch.object(broker, "candidates", side_effect=candidate_set) as candidates, \
         mock.patch.object(broker, "_strict_env", return_value={}), \
         mock.patch.object(broker, "_ollama_chat", return_value=response) as local, \
         mock.patch.object(broker, "_gemini_chat") as cloud:
        result = broker.chat(
            [{"role": "user", "content": "inspect the repository"}],
            tools=[{"type": "function", "function": {"name": "shell"}}],
            privacy="local-only",
            task_class="substantial",
        )

    assert candidates.call_count == 1
    local.assert_called_once()
    cloud.assert_not_called()
    assert result["provider"] == "ollama"
    assert result["finish_reason"] == "tool_calls"


def test_local_only_tool_chat_fails_closed_after_local_provider_failure():
    provider = {"id": "ollama", "api_model": "qwen2.5-coder:7b-instruct"}
    with mock.patch.object(
        broker,
        "candidates",
        return_value=([provider], [{"provider": "ollama", "status": "AVAILABLE"}]),
    ) as candidates, mock.patch.object(broker, "_strict_env", return_value={}), \
         mock.patch.object(broker, "_ollama_chat", side_effect=broker.BrokerError("local unavailable")), \
         mock.patch.object(broker, "_gemini_chat") as cloud:
        try:
            broker.chat(
                [{"role": "user", "content": "inspect private source"}],
                tools=[{"type": "function", "function": {"name": "shell"}}],
                privacy="local-only",
            )
        except broker.BrokerError as exc:
            assert "tool-capable providers exhausted" in str(exc)
        else:
            raise AssertionError("local-only tool failure did not fail closed")

    assert candidates.call_count == 1
    cloud.assert_not_called()
