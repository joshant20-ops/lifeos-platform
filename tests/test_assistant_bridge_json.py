"""The Home Assistant assistant requests native local JSON output."""
import importlib.util
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[1]
GOVERNOR = REPO / "governor"
sys.path.insert(0, str(GOVERNOR))
SPEC = importlib.util.spec_from_file_location(
    "lifeos_assistant_bridge", GOVERNOR / "assistant_bridge.py"
)
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


def test_assistant_uses_local_json_mode_for_model_backed_conversation(monkeypatch):
    calls = []
    monkeypatch.setattr(BRIDGE, "process_pa_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(BRIDGE, "pa_structured_answer", lambda _question: None)
    monkeypatch.setattr(
        BRIDGE,
        "generate",
        lambda prompt, **kwargs: calls.append(kwargs)
        or {"text": '{"reply":"ok"}', "provider": "ollama"},
    )

    result = BRIDGE.analyse(
        [{"role": "user", "content": "Check overall health, read-only."}],
        privacy_domain="personal-administration",
    )

    assert result["reply"] == "ok"
    assert result["privacy"] == "local-only"
    assert calls == [{"privacy": "local-only", "task_class": "normal", "response_format": "json"}]
