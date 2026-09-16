import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engineer"))

from cleanup_audit import classify
from provider_router import PolicyError, load_policy, load_secret_names, route
from review_packet import build


def policy():
    return load_policy(ROOT / "governor/policy.json")


def test_missing_credentials_are_reported_and_next_free_provider_selected():
    result = route(
        policy(),
        "normal",
        {"GROQ_API_KEY"},
        available_adapters={"direct-cloud", "codex"},
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
        available_adapters={"direct-cloud", "codex"},
    )
    assert result["selected_provider"] == "groq"
    gemini = next(x for x in result["considered"] if x["provider"] == "gemini")
    assert gemini["status"] == "COOLDOWN"


def test_local_only_never_selects_cloud_or_codex():
    result = route(
        policy(),
        "normal",
        {"GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"},
        privacy="local-only",
        available_adapters={"local-builder", "direct-cloud", "codex"},
    )
    assert result["selected_provider"] == "ollama"
    forbidden = [
        x for x in result["considered"]
        if x["provider"] in {"gemini", "groq", "openrouter", "cloudflare", "codex"}
    ]
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
        available_adapters={"direct-cloud", "codex"},
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


def test_cloud_providers_are_direct_and_have_api_models():
    providers = [item for item in policy()["providers"] if item.get("adapter") == "direct-cloud"]
    assert {item["id"] for item in providers} == {"gemini", "groq", "openrouter", "cloudflare"}
    assert all(item.get("api_model") for item in providers)
    assert all(item.get("privacy") == "sanitized-cloud" for item in providers)
    assert all(not item.get("openhands_model") for item in providers)


def test_openhands_worker_uses_only_governor_broker_capability(tmp_path):
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
    task.write_text("Make no changes; validate broker routing only.\n")
    broker = tmp_path / "broker.env"
    broker.write_text(
        "LIFEOS_GOVERNOR_BROKER_URL=http://192.0.2.1:8791/v1\n"
        "LIFEOS_GOVERNOR_BROKER_TOKEN=broker-only-secret\n"
    )
    broker.chmod(0o600)

    fake = tmp_path / "openhands"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os,sys\n"
        "assert '--headless' in sys.argv and '--override-with-envs' in sys.argv and '-t' in sys.argv\n"
        "assert os.environ['LIFEOS_PROVIDER'] == 'governor-broker'\n"
        "assert os.environ['LLM_MODEL'] == 'openai/lifeos-normal'\n"
        "assert os.environ['LLM_BASE_URL'] == 'http://192.0.2.1:8791/v1'\n"
        "assert os.environ['LLM_API_KEY'] == 'broker-only-secret'\n"
        "assert 'GEMINI_API_KEY' not in os.environ and 'GROQ_API_KEY' not in os.environ\n"
        "sys.exit(0)\n"
    )
    fake.chmod(0o755)

    done = subprocess.run(
        [
            sys.executable,
            ROOT / "engineer/openhands_worker.py",
            "--repo", repo,
            "--task", task,
            "--broker-config", broker,
            "--execute",
            "--openhands-command", fake,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    evidence = json.loads(done.stdout)
    assert evidence["selected_provider"] == "governor-broker"
    assert evidence["inference_authority"] == "pi5-governor"
    assert evidence["result"] == "PASS"
    assert evidence["concurrent_main_unchanged"] is True
    assert subprocess.check_output(["git", "-C", repo, "rev-parse", "main"], text=True).strip() == main_before
    assert "broker-only-secret" not in done.stdout


def test_openhands_private_job_requests_local_only_broker_model(tmp_path):
    from openhands_worker import broker_environment

    broker = tmp_path / "broker.env"
    broker.write_text(
        "LIFEOS_GOVERNOR_BROKER_URL=http://192.0.2.1:8791/v1\n"
        "LIFEOS_GOVERNOR_BROKER_TOKEN=secret\n"
    )
    broker.chmod(0o600)
    env = broker_environment(broker, "local-only")
    assert env["LLM_MODEL"] == "openai/lifeos-local-only-normal"


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


def test_remote_agent_attempt_has_bounded_deadline_and_timeout_evidence():
    script = (ROOT / "governor/scripts/lifeos-remote-agent-builder").read_text()
    assert "AGENT_TIMEOUT_SECONDS=${LIFEOS_AGENT_TIMEOUT_SECONDS:-600}" in script
    assert '/usr/bin/timeout --signal=TERM --kill-after=15s "${AGENT_TIMEOUT_SECONDS}s"' in script
    assert 'HANDOFF_ERROR=agent_timeout_${AGENT_TIMEOUT_SECONDS}s' in script
    assert "AGENT_TIMEOUT_SECONDS >= 60 && AGENT_TIMEOUT_SECONDS <= 1200" in script


def test_governor_deploy_repeats_proven_wol_until_wall_clock_deadline():
    workflow = (ROOT / ".github/workflows/lifeos-governor-broker-deploy.yml").read_text()
    preflight = workflow.split("- name: Ensure Engineer available for deploy preflight", 1)[1]
    preflight = preflight.split("- name: Deploy Governor with live phase checkpoints", 1)[0]
    assert "deadline=$((SECONDS + 600))" in preflight
    assert "while (( SECONDS < deadline ))" in preflight
    assert "/usr/local/sbin/lifeos-engineer-wake" in preflight
    assert "/usr/local/sbin/lifeos-tower-wake" in preflight
    assert "wake_engineer()" in preflight
    assert preflight.count("wake_engineer") >= 3
    assert preflight.count("wakeonlan 40:8d:5c:84:41:64") == 1
    assert "attempt % 6 == 0" in preflight
    assert "ENGINEER_PREFLIGHT_WAKE_RETRY=" in preflight


def test_governor_deploy_runs_true_autonomous_e2e_gate():
    workflow = (ROOT / ".github/workflows/lifeos-governor-broker-deploy.yml").read_text()
    assert "LIFEOS_SKIP_AUTONOMOUS_E2E=1" not in workflow
    assert "timeout-minutes: 45" in workflow
    deploy = (ROOT / "governor/scripts/deploy-autonomous-agent-pi5.sh").read_text()
    assert "AUTONOMOUS_LOOP=PASS" in deploy
    agent = (ROOT / "governor/autonomous_agent.py").read_text()
    assert 'set_stage(job, "verifier"' in agent


def test_autonomous_e2e_respects_read_only_canonical_checkout():
    deploy = (ROOT / "governor/scripts/deploy-autonomous-agent-pi5.sh").read_text()
    smoke = deploy.split("SMOKE_REQ=", 1)[1].split("SMOKE_JSON=", 1)[0]
    assert "Do not modify the repository" in smoke
    assert "do not return a Pi runtime launcher" in smoke
    assert "create the required per-job Pi5 runtime launcher" not in smoke
    assert "GOVERNOR_ENGINEER_TOOL_ACTION=PASS" in deploy
    assert "LOCAL_VERIFIER=PASS" in deploy
    assert "missing local verifier PASS evidence" in deploy


def test_openhands_smoke_uses_bounded_repeated_engineer_wake():
    workflow = (ROOT / ".github/workflows/lifeos-openhands-action-smoke.yml").read_text()
    wake = workflow.split("- name: Ensure Engineer available", 1)[1]
    wake = wake.split("- name: Prove authenticated Governor tool route", 1)[0]
    assert "deadline=$((SECONDS + 600))" in wake
    assert "while (( SECONDS < deadline ))" in wake
    assert "/usr/local/sbin/lifeos-engineer-wake" in wake
    assert "wake_engineer()" in wake
    assert wake.count("wake_engineer") >= 3
    assert "attempt % 6 == 0" in wake


def test_openhands_smoke_normalizes_optional_terminal_newline():
    workflow = (ROOT / ".github/workflows/lifeos-openhands-action-smoke.yml").read_text()
    assert "p.read_text().splitlines()" in workflow
    assert "actual == expected" in workflow


def test_cloud_builder_preserves_bundle_across_retries_and_streams_evidence():
    script = (ROOT / "governor/scripts/lifeos-cloud-builder").read_text()
    assert 'trap \'rm -f "$SNAPSHOT"\' EXIT' not in script
    assert 'trap \'rm -f "$HELPER" "$SNAPSHOT"\' EXIT' not in script
    assert 'trap cleanup EXIT' in script
    assert '| tee "$ATTEMPT_LOG"' in script
    assert 'RC=${PIPESTATUS[0]}' in script
    assert "OUTPUT=$(ssh" not in script
