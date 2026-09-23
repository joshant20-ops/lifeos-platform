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


def test_stable_base_selects_codex_and_excludes_private_local():
    result = route(
        policy(),
        "normal",
        {"GROQ_API_KEY"},
        available_adapters={"local-builder", "codex"},
    )
    assert result["selected_provider"] == "codex"
    assert {x["provider"] for x in result["considered"]} == {"ollama", "codex"}
    local = next(x for x in result["considered"] if x["provider"] == "ollama")
    assert local["status"] == "PRIVACY_FORBIDDEN"
    assert result["max_attempts"] == 2


def test_private_local_cooldown_fails_closed_without_codex_fallback():
    result = route(
        policy(),
        "normal",
        {"GEMINI_API_KEY", "GROQ_API_KEY"},
        {"ollama": 101},
        now=100, privacy="local-only",
        available_adapters={"local-builder", "codex"},
    )
    assert result["selected_provider"] is None
    local = next(x for x in result["considered"] if x["provider"] == "ollama")
    assert local["status"] == "COOLDOWN"
    codex = next(x for x in result["considered"] if x["provider"] == "codex")
    assert codex["status"] == "PRIVACY_FORBIDDEN"


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


def test_adapter_availability_is_part_of_private_routing_decision():
    result = route(policy(), "normal", set(), privacy="local-only", available_adapters={"codex"})
    assert result["selected_provider"] is None
    ollama = next(x for x in result["considered"] if x["provider"] == "ollama")
    assert ollama["status"] == "ADAPTER_UNAVAILABLE"


def test_review_requires_capable_provider():
    result = route(
        policy(),
        "review",
        {"GEMINI_API_KEY"},
        available_adapters={"direct-cloud", "codex"},
    )
    assert result["selected_provider"] == "codex"
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


def test_stable_base_has_no_direct_cloud_providers_and_codex_is_sanitized():
    providers = [item for item in policy()["providers"] if item.get("adapter") == "direct-cloud"]
    assert providers == []
    codex = next(item for item in policy()["providers"] if item["id"] == "codex")
    assert codex["adapter"] == "codex"
    assert codex["privacy"] == "sanitized-cloud"


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
    assert 'echo "ENGINEER_PREFLIGHT_BOOT_GRACE_SECONDS=120"' in preflight
    assert "sleep 120" in preflight
    assert "deadline=$((SECONDS + 480))" in preflight
    assert "while (( SECONDS < deadline ))" in preflight
    assert "/usr/local/sbin/lifeos-engineer-wake" in preflight
    assert "/usr/local/sbin/lifeos-tower-wake" in preflight
    assert "wake_engineer()" in preflight
    assert preflight.count("wake_engineer") >= 3
    assert preflight.count("wakeonlan 40:8d:5c:84:41:64") == 1
    assert "attempt % 6 == 0" in preflight
    assert "ENGINEER_PREFLIGHT_WAKE_RETRY=" in preflight


def test_governor_deploy_proves_interfaces_without_competing_engineering_job():
    deploy = (ROOT / "governor/scripts/deploy-autonomous-agent-pi5.sh").read_text()
    assert "AUTONOMOUS_E2E=DELEGATED_TO_MISSION_WORKFLOW" in deploy
    assert "AUTONOMOUS_E2E_REASON=deployment_proves_interfaces_mission_proves_engineering" in deploy
    assert "SMOKE_REQ=" not in deploy
    assert "AUTONOMOUS_LOOP=PASS" not in deploy

    workflow = (ROOT / ".github/workflows/lifeos-governor-broker-deploy.yml").read_text()
    assert "timeout-minutes: 45" in workflow


def test_level1_worker_does_not_own_meta_issue_disposition():
    mission = (ROOT / "governor/scripts/lifeos-pa-mission").read_text()
    assert "Do not close GitHub issues" in mission
    assert "LEVEL1_CANONICAL_MARKER=PASS" in mission
    assert "LEVEL1_DETERMINISTIC_ASSERTION=PASS" in mission
    assert 'passed = status == "PASS"' in mission
    assert 'passed = canonical_marker' in mission
    assert 'if passed and target == "759":' in mission


def test_warning_only_audit_does_not_override_targeted_mission_pass():
    mission = (ROOT / "governor/scripts/lifeos-pa-mission").read_text()
    assert 'blocking_faults = any(' in mission
    assert 'in {"high", "critical"}' in mission
    assert 'or blocking_faults:' in mission
    assert 'or faults:' not in mission


def test_governed_pipeline_smoke_owns_openhands_routing_proof():
    workflow = (ROOT / ".github/workflows/lifeos-governed-pipeline-smoke.yml").read_text()
    assert "bash scripts/test-engineer-governor-broker.sh" in workflow
    assert "bash scripts/test-direct-openhands.sh" in workflow
    assert "tests/test_governor_local_tool_routing.py" in workflow
    assert "- name: Direct OpenHands governed routing proof" in workflow


def test_cloud_builder_preserves_bundle_across_retries_and_streams_evidence():
    script = (ROOT / "governor/scripts/lifeos-cloud-builder").read_text()
    assert 'trap \'rm -f "$SNAPSHOT"\' EXIT' not in script
    assert 'trap \'rm -f "$HELPER" "$SNAPSHOT"\' EXIT' not in script
    assert 'trap cleanup EXIT' in script
    assert '| tee "$ATTEMPT_LOG"' in script
    assert 'RC=${PIPESTATUS[0]}' in script
    assert "OUTPUT=$(ssh" not in script


def test_cloud_builder_codex_exhaustion_falls_back_local_only_to_tower_ollama():
    script = (ROOT / "governor/scripts/lifeos-cloud-builder").read_text()
    assert 'if [[ "$PRIVACY" == "local-only" ]]' in script
    assert 'REASON=cloud_builder_forbidden_for_local_only_job' in script
    assert 'CLOUD_AGENTS_EXHAUSTED=YES' in script
    assert 'FALLBACK_ROUTE=Tower_Ollama' in script
    assert 'LIFEOS_JOB_PRIVACY=local-only' in script
    assert '"$LOCAL_BUILDER" "$REQUEST" "$ITERATION" "$FEEDBACK"' in script
    assert 'FALLBACK_RESULT=local_builder PASS' in script


def test_openhands_sdk_runner_requires_real_tool_activity():
    runner = (ROOT / "governor/scripts/lifeos-openhands-sdk-runner.py").read_text()
    assert "AgentErrorEvent" in runner
    assert "OPENHANDS_SDK_ERROR=no_engineering_tool_activity" in runner
    assert "OPENHANDS_SDK_TOOL_EVENTS=" in runner
    assert 'if not tool_events:' in runner


def test_openhands_sdk_runner_reads_events_from_conversation_state():
    runner = (ROOT / "governor/scripts/lifeos-openhands-sdk-runner.py").read_text()
    assert "conversation.run()" in runner
    assert "events = list(conversation.state.events)" in runner
    assert "events = conversation.run()" not in runner


def test_openhands_sdk_runner_requires_autonomous_repository_completion_prompt():
    runner = (ROOT / "governor/scripts/lifeos-openhands-sdk-runner.py").read_text()
    assert "Do not stop at describing, summarising, planning, or proposing commands." in runner
    assert "execute the requested work with native tools" in runner
    assert "Before finishing, run at least one focused deterministic command" in runner


def test_openhands_sdk_runner_requires_tool_grounded_repository_discovery_first():
    runner = (ROOT / "governor/scripts/lifeos-openhands-sdk-runner.py").read_text()
    first_action = runner.index("Your first action must use the native terminal tool")
    no_guessing = runner.index("never guess a file or directory")
    perform_work = runner.index("execute the requested work with native tools")
    assert first_action < no_guessing < perform_work
    assert "inspect the repository's real top-level structure" in runner
    assert "re-list the relevant parent before creating a new path" in runner


def test_openhands_sdk_runner_uses_ots_cli_autonomous_agent_preset():
    runner = (ROOT / "governor/scripts/lifeos-openhands-sdk-runner.py").read_text()
    builder = (ROOT / "governor/scripts/lifeos-remote-agent-builder").read_text()
    assert "from openhands_cli.utils import get_default_cli_agent" in runner
    assert "agent = get_default_cli_agent(llm)" in runner
    assert "Agent(" not in runner
    assert "get_default_cli_agent" in builder
    assert "OPENHANDS_NATIVE_ENGINEERING_PRESET=cli_default" in builder


def test_local_ai_cold_start_allows_full_tower_boot_window():
    broker = (ROOT / "governor/ai_broker.py").read_text()
    builder = (ROOT / "governor/scripts/lifeos-local-builder").read_text()
    assert 'LIFEOS_LOCAL_AI_WAKE_TIMEOUT", "180"' in broker
    assert "m._publish_lease('active')" in builder
    assert "m._wake_local_ai()" in builder
    assert "for attempt in $(seq 1 70)" in builder
    assert "engineer_not_ready_after_210s_local_tower_wake" in builder


def test_openhands_sdk_requires_concrete_audit_evidence():
    runner = (ROOT / "governor/scripts/lifeos-openhands-sdk-runner.py").read_text()
    assert "actually enumerate and inspect the relevant repository estate" in runner
    assert "Before finishing, run at least one focused deterministic command" in runner
    assert "Treat prior Governor verifier instructions as mandatory work" in runner
