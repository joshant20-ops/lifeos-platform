import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stable_ai_broker", ROOT / "governor/ai_broker.py")
BROKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROKER)


def test_normal_broker_request_cannot_use_private_only_ollama():
    eligible, considered = BROKER.candidates(privacy="normal", task_class="normal")
    assert eligible == []
    local = next(x for x in considered if x["provider"] == "ollama")
    assert local["status"] == "PRIVACY_FORBIDDEN"


def test_private_broker_request_can_use_ollama():
    eligible, _ = BROKER.candidates(privacy="local-only", task_class="normal")
    assert [x["id"] for x in eligible] == ["ollama"]
