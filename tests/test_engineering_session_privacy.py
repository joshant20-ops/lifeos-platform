import importlib.machinery
import importlib.util
import pathlib
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "governor/autonomous_agent_server.py"


def _load_server(monkeypatch):
    core = types.SimpleNamespace(
        classify_privacy=lambda text: "local-only" if "private documents" in text.lower() else "normal",
        Handler=object,
        PORT=8790,
    )
    broker = types.SimpleNamespace(BrokerError=RuntimeError)
    compat = types.SimpleNamespace()

    original = importlib.machinery.SourceFileLoader.exec_module

    def fake_exec(loader, module):
        path = str(loader.path)
        if path.endswith("lifeos-autonomous-agent-core"):
            module.classify_privacy = core.classify_privacy
            module.Handler = core.Handler
            module.PORT = core.PORT
            return
        if path.endswith("ai_broker.py"):
            module.BrokerError = RuntimeError
            return
        if path.endswith("openai_compat.py"):
            return
        return original(loader, module)

    monkeypatch.setattr(importlib.machinery.SourceFileLoader, "exec_module", fake_exec)
    loader = importlib.machinery.SourceFileLoader("server_under_test", str(SERVER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_engineering_session_classifies_user_turns_not_repo_tool_output(monkeypatch):
    server = _load_server(monkeypatch)
    messages = [
        {"role": "user", "content": "Refactor the routing tests."},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "Repository policy mentions private documents."},
    ]
    text = server._privacy_text(messages, roles={"user"})
    assert "Refactor the routing tests." in text
    assert "private documents" not in text
    assert server.CORE.classify_privacy(text) == "normal"


def test_engineering_session_still_fails_closed_for_private_user_prompt(monkeypatch):
    server = _load_server(monkeypatch)
    messages = [{"role": "user", "content": "Summarise my private documents."}]
    text = server._privacy_text(messages, roles={"user"})
    assert server.CORE.classify_privacy(text) == "local-only"


def test_cloud_builder_uses_dedicated_engineering_model():
    script = (ROOT / "governor/scripts/lifeos-cloud-builder").read_text()
    assert "openai/lifeos-engineering-${TASK_CLASS}" in script
