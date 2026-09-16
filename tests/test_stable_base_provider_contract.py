import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engineer"))

from provider_router import load_policy, route


def policy():
    return load_policy(ROOT / "governor/policy.json")


def test_private_normal_task_routes_only_to_local_ollama():
    result = route(
        policy(), "normal", set(), privacy="local-only",
        available_adapters={"local-builder", "codex"},
    )
    assert result["selected_provider"] == "ollama"
    codex = next(x for x in result["considered"] if x["provider"] == "codex")
    assert codex["status"] == "PRIVACY_FORBIDDEN"


def test_nonpersonal_normal_task_routes_to_codex_not_private_local():
    result = route(
        policy(), "normal", set(), privacy="normal",
        available_adapters={"local-builder", "codex"},
    )
    assert result["selected_provider"] == "codex"
    ollama = next(x for x in result["considered"] if x["provider"] == "ollama")
    assert ollama["status"] == "PRIVACY_FORBIDDEN"


def test_only_local_and_codex_ai_providers_are_active():
    ids = {p["id"] for p in policy()["providers"] if p["id"] != "deterministic"}
    assert ids == {"ollama", "codex"}
