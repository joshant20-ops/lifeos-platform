import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engineer"))
from provider_router import load_policy, route


def test_private_only_flag_excludes_local_from_normal_routing():
    policy = load_policy(ROOT / "governor/policy.json")
    result = route(policy, "normal", set(), privacy="normal", available_adapters={"local-builder", "codex"})
    assert result["selected_provider"] == "codex"
    local = next(x for x in result["considered"] if x["provider"] == "ollama")
    assert local["status"] == "PRIVACY_FORBIDDEN"
