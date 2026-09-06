import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engineer"))

from cleanup_audit import classify
from provider_router import PolicyError, load_policy, load_secret_names, openhands_environment, route
from review_packet import build


def policy():
    return load_policy(ROOT / "governor/policy.json")


def test_missing_credentials_are_reported_and_next_free_provider_selected():
    result = route(
        policy(),
        "normal",
        {"GROQ_API_KEY"},
        available_adapters={"openhands", "codex"},
    )
    assert result["selected_provider"] == "groq"
    gemini = next(x for x in result["considered"] if x["provider"] == "gemini")
    assert gemini["status"] == "CREDENTIAL_REQUIRED"
    assert result["max_attempts"] == 2


def test_cooldown_routes_without_retry_storm():
    result = route(
        policy(),
        "normal",
        {"GEMINI_API_KEY", "GROQ_API_KEY"},
        {"gemini": 101},
        now=100,
        available_adapters={"openhands", "codex"},
    )
    assert result["selected_provider"] == "groq"
    gemini = next(x for x in result["considered"] if x["provider"] == "gemini")
    assert gemini["status"] == "COOLDOWN"


def test_local_only_never_selects_cloud_or_codex():
    result = route(
        policy(),
        "normal",
        {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"},
        privacy="local-only",
        available_adapters={"local-builder", "openhands", "codex"},
    )
    assert result["selected_provider"] == "ollama"
    forbidden = [x for x in result["considered"] if x["provider"] in {"gemini", "groq", "openrouter", "codex"}]
    assert forbidden and all(x["status"] == "PRIVACY_FORBIDDEN" for x in forbidden)


def test_adapter_availability_is_part_of_routing_decision():
    result = route(policy(), "normal", set(), available_adapters={"codex"})
    assert result["selected_provider"] == "codex"
    ollama = next(x for x in result["considered"] if x["provider"] == "ollama")
    assert ollama["status"] == "ADAPTER_UNAVAILABLE"


def test_review_requires_capable_provider():
    result = route(
        policy(),
        "review",
        {"GEMINI_API_KEY"},
        available_adapters={"openhands", "codex"},
    )
    assert result["selected_provider"] == "gemini"
    assert result["considered"][0]["capability"] >= 4


def test_secret_file_requires_exact_0600_and_never_returns_values(tmp_path):
    secret = tmp_path / "providers.env"
    secret.write_text("GEMINI_API_KEY=do-not-log\n")
    secret.chmod(0o644)
    try:
        load_secret_names(secret)
        assert False
    except PolicyError:
        pass
    secret.chmod(0o600)
    assert load_secret_names(secret) == {"GEMINI_API_KEY"}


def test_openhands_environment_maps_governor_model_and_selected_secret(tmp_path):
    secret = tmp_path / "providers.env"
    secret.write_text("GEMINI_API_KEY=selected-secret\nGROQ_API_KEY=must-not-leak\n")
    secret.chmod(0o600)
    provider = next(item for item in policy()["providers"] if item["id"] == "gemini")
    env = openhands_environment(provider, secret)
    assert env["LLM_MODEL"].startswith("gemini/")
    assert env["LLM_API_KEY"] == "selected-secret"
    assert env["GEMINI_API_KEY"] == "selected-secret"
    assert "GROQ_API_KEY" not in env


def test_everyday_cloud_providers_have_explicit_openhands_models():
    providers = [item for item in policy()["providers"] if item.get("adapter") == "openhands"]
    assert {item["id"] for item in providers} == {"gemini", "groq", "openrouter", "cloudflare"}
    assert all(item.get("openhands_model") for item in providers)
    assert all(item.get("privacy") == "sanitized-cloud" for item in providers)


def test_worker_retries_then_fails_over_without_mutating_main(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", repo], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "Test"], check=True)
    (repo / "README").write_text("fixture\n")
    subprocess.run(["git", "-C", repo, "add", "README"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-m", "fixture"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "switch", "-c", "engineer/test"], check=True, capture_output=True)
    main_before = subprocess.check_output(["git", "-C", repo, "rev-parse", "main"], text=True).strip()
    task = tmp_path / "task.txt"
    task.write_text("Make no changes; validate routing only.\n")
    secrets = tmp_path / "providers.env"
    secrets.write_text("GEMINI_API_KEY=gemini-secret\nGROQ_API_KEY=groq-secret\n")
    secrets.chmod(0o600)
    fake = tmp_path / "openhands"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os,sys\n"
        "assert '--headless' in sys.argv and '--override-with-envs' in sys.argv and '-t' in sys.argv\n"
        "sys.exit(7 if os.environ['LIFEOS_PROVIDER'] == 'gemini' else 0)\n"
    )
    fake.chmod(0o755)
    done = subprocess.run(
        [
            sys.executable,
            ROOT / "engineer/openhands_worker.py",
            "--repo",
            repo,
            "--task",
            task,
            "--secrets",
            secrets,
            "--execute",
            "--openhands-command",
            fake,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    evidence = json.loads(done.stdout)
    assert [(x["provider"], x["attempt"]) for x in evidence["attempts"]] == [
        ("gemini", 1),
        ("gemini", 2),
        ("groq", 1),
    ]
    assert evidence["attempts"][1]["cooldown_seconds"] == 900
    assert evidence["selected_provider"] == "groq" and evidence["result"] == "PASS"
    assert evidence["concurrent_main_unchanged"] is True
    assert subprocess.check_output(["git", "-C", repo, "rev-parse", "main"], text=True).strip() == main_before
    assert "gemini-secret" not in done.stdout and "groq-secret" not in done.stdout


def test_cleanup_is_dry_run_and_never_classifies_safe_to_remove(tmp_path):
    (tmp_path / ".openhands").mkdir()
    (tmp_path / ".openhands.backup").mkdir()
    result = classify(tmp_path)
    assert result["automatic_deletion"] == "DISABLED" and result["safe_to_remove"] == []
    assert any(x["classification"] == "REVIEW_REQUIRED" for x in result["items"])


def test_policy_is_valid_json_and_paid_fallback_is_off_by_default():
    item = json.loads((ROOT / "governor/policy.json").read_text())
    assert item["schema_version"] == 3
    assert item["routing"]["strategy"] == "cheapest-capable"
    assert item["routing"]["allow_paid_fallback"] is False


def test_review_packet_is_compact_metadata_not_repository_content():
    result = build(ROOT)
    assert result["provider_role"] == "codex-senior-review"
    assert result["content_included"] is False
    assert len(json.dumps(result)) < 16000
