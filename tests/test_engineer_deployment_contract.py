import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "governor/scripts/deploy-engineer-ai.sh"
BACKEND = ROOT / "governor/engineer_backend.py"
RUNTIME = ROOT / "governor/runtime_jobs/ebf8a71d4bff.sh"
JOB_RUNTIME = ROOT / "governor/runtime_jobs/feb1efaecf51.sh"


def test_engineer_backend_exposes_health_readiness_endpoint():
    backend = BACKEND.read_text()
    assert 'if self.path in ("/health", "/v1/health"):' in backend
    assert 'self.send_json(200, {"service": "lifeos-engineer", "status": "ok"' in backend
    assert 'self.send_json(503, {"service": "lifeos-engineer", "status": "degraded"' in backend


def test_readiness_uses_health_and_full_backoff_budget():
    assert os.access(DEPLOY, os.X_OK)
    script = DEPLOY.read_text()
    assert 'UI_HEALTH_URL="http://127.0.0.1:${OWUI_PORT}/health"' in script
    assert 'wait_for_health OPEN_WEBUI_EXISTING "$UI_HEALTH_URL" 300' in script
    assert 'wait_for_health OPEN_WEBUI "$UI_HEALTH_URL" 300' in script
    assert "(( delay < 16 )) &&" not in script
    assert "if (( delay < 16 )); then" in script


def test_healthy_running_ui_is_reused_before_any_removal():
    script = DEPLOY.read_text()
    reuse = script.index("OPEN_WEBUI_REUSED=healthy_existing_container source=docker_health")
    removal = script.index('docker rm -f "$UI_NAME"')
    assert reuse < removal
    assert "RECREATE_UI=false" in script[reuse:removal]


def test_docker_health_prevents_destruction_during_host_probe_failure():
    script = DEPLOY.read_text()
    existing = script[script.index("RECREATE_UI=true"):script.index('if [[ "$RECREATE_UI" == true ]]')]
    assert "UI_DOCKER_HEALTH=$(ui_container_health)" in existing
    assert '[[ "$UI_DOCKER_HEALTH" == healthy ]]' in existing
    assert '[[ "$(ui_container_health)" == healthy ]]' in existing
    assert existing.count("RECREATE_UI=false") == 3
    assert existing.index('[[ "$UI_DOCKER_HEALTH" == healthy ]]') < existing.index("wait_for_health OPEN_WEBUI_EXISTING")
    assert existing.index('[[ "$(ui_container_health)" == healthy ]]') > existing.index("wait_for_health OPEN_WEBUI_EXISTING")


def test_failure_diagnostics_and_safe_ha_rollback_are_present():
    deploy = DEPLOY.read_text()
    runtime = RUNTIME.read_text()
    assert "docker logs --tail 200 --timestamps" in deploy
    assert "journalctl -u lifeos-engineer.service -n 200" in deploy
    assert "rollback_ha || true" in runtime
    assert "HA_ROLLBACK=PASS" in runtime
    assert "HA_ROLLBACK_RESTART=PASS" in runtime
    assert "HA_RESTARTED=true" in runtime
    assert "home_assistant_cannot_reach_engineer" in runtime
    assert 'docker logs --tail 200 --timestamps "$HA_CONTAINER"' in runtime
    assert "python3 -m homeassistant --script check_config -c /config || true" in runtime
    assert "(( delay < 16 )) &&" not in runtime


def test_unexpected_deployment_failures_emit_phase_diagnostics():
    deploy = DEPLOY.read_text()
    assert "trap 'unexpected_failure \"$LINENO\"' ERR" in deploy
    assert "DEPLOYMENT_FAILURE=unexpected phase=%s line=%s exit=%s" in deploy
    handler = deploy[deploy.index("unexpected_failure() {"):deploy.index("ui_container_health() {")]
    assert "trap - ERR" in handler
    assert "open_webui|verification) ui_diagnostics; backend_diagnostics" in handler
    assert 'timeout 300 docker pull "$OWUI_IMAGE"' in deploy


def test_ha_rollback_reactivates_restored_config_after_restart():
    runtime = RUNTIME.read_text()
    rollback = runtime[runtime.index("rollback_ha() {"):runtime.index("fail() {")]
    assert '[[ "$ROLLING_BACK" == false ]] || {' in rollback
    assert 'if [[ "$HA_RESTARTED" == true && -n "$HA_CONTAINER" ]]; then' in rollback
    assert 'timeout 120 docker restart "$HA_CONTAINER"' in rollback
    assert "wait_url http://127.0.0.1:8123/ 180" in rollback


def test_failure_handler_cannot_recursively_trap_rollback_errors():
    runtime = RUNTIME.read_text()
    failure = runtime[runtime.index("fail() {"):runtime.index("wait_url() {")]
    assert "FAILURE_ACTIVE=true" in failure
    assert "trap - ERR" in failure
    assert "rollback_ha || true" in failure
    assert failure.index("trap - ERR") < failure.index("rollback_ha || true")
    rollback = runtime[runtime.index("rollback_ha() {"):runtime.index("fail() {")]
    assert "HA_ROLLBACK=FAIL reason=restored_config_restart_failed" in rollback
    assert "HA_ROLLBACK=FAIL reason=restored_config_startup_timeout" in rollback


def test_runtime_signals_trigger_transactional_ha_rollback():
    runtime = RUNTIME.read_text()
    assert "trap 'fail runtime_terminated' TERM" in runtime
    assert "trap 'fail runtime_interrupted' INT" in runtime


def test_new_ui_exposes_docker_health_from_health_endpoint():
    script = DEPLOY.read_text()
    assert '--health-cmd=' in script
    assert "http://127.0.0.1:8080/health" in script
    assert "--health-start-period=300s" in script
    assert "--health-retries=3" in script


def test_runtime_waits_for_ha_and_verifies_registered_panel_route():
    runtime = RUNTIME.read_text()
    reachability = runtime.index('timeout 30 docker exec "$HA_CONTAINER"')
    assert runtime.index("wait_url http://127.0.0.1:8123/ 180") < reachability
    assert "HA_ROUTE_CODE=$(curl" in runtime
    assert "http://127.0.0.1:8123/lifeos_engineer" in runtime
    assert 'HA_PANEL_ROUTE=PASS status=%s' in runtime
    assert 'curl -sS -i --max-time 10 "$BACKEND_HEALTH"' in runtime
    assert 'curl -sS -i --max-time 10 "$UI_HEALTH"' in runtime


def test_ha_include_only_change_is_validated_and_activated():
    runtime = RUNTIME.read_text()
    panel_update = runtime.index('if [[ -f "$HA_PANEL" ]] && cmp -s')
    activation = runtime.index('if [[ "$HA_CHANGED" == true ]]; then', panel_update)
    route_check = runtime.index("HA_ROUTE_CODE=$(curl", activation)
    activation_block = runtime[activation:route_check]
    assert 'python3 -m homeassistant --script check_config' in activation_block
    assert 'HA_RESTARTED=true' in activation_block
    assert 'docker restart "$HA_CONTAINER"' in activation_block
    assert 'HA_CONFIGURATION=ACTIVATED' in activation_block


def test_ha_rollback_snapshot_is_unique_for_rapid_retries():
    runtime = RUNTIME.read_text()
    assert 'BACKUP_ROOT="$HA_CONFIG_DIR/.lifeos-backups"' in runtime
    assert 'BACKUP_DIR=$(mktemp -d "$BACKUP_ROOT/engineer-panel-' in runtime
    assert "home_assistant_backup_creation_failed" in runtime
    assert 'BACKUP_DIR="$HA_CONFIG_DIR/.lifeos-backups/engineer-panel-$(date' not in runtime


def test_runtime_discovers_real_lan_address_and_nonstandard_ha_container():
    runtime = RUNTIME.read_text()
    assert "ip -4 route get 192.168.0.201" in runtime
    assert "pi5_lan_address_not_found" in runtime
    assert "{{.Names}}|{{.Ports}}" in runtime
    assert "8123->8123\\/tcp" in runtime
    assert "HA_CONTAINER=$(discover_ha_container)" in runtime


def test_current_job_launcher_is_timeout_aware_and_preserves_runtime_evidence():
    assert os.access(JOB_RUNTIME, os.X_OK)
    launcher = JOB_RUNTIME.read_text()
    assert launcher.startswith("#!/usr/bin/env bash\n")
    assert 'readonly OUTER_TIMEOUT_SECONDS=3600' in launcher
    assert 'readonly ROLLBACK_GRACE_SECONDS=360' in launcher
    assert 'timeout --signal=TERM --kill-after="${ROLLBACK_GRACE_SECONDS}s"' in launcher
    assert 'env LIFEOS_RUNTIME_JOB_ID="$JOB_ID" "$RUNTIME"' in launcher
    assert "readonly JOB_ID=feb1efaecf51" in launcher
    assert "RUNTIME_CHECK=PASS" in launcher
    assert "runtime_timeout" in launcher


def test_runtime_proves_healthy_container_identity_is_preserved():
    runtime = RUNTIME.read_text()
    before = runtime.index("HEALTHY_UI_ID_BEFORE=$(docker inspect")
    deploy = runtime.index('timeout "$TIMEOUT_SECONDS" "$DEPLOY"')
    after = runtime.index("HEALTHY_UI_ID_AFTER=$(docker inspect")
    assert before < deploy < after
    assert '[[ "$HEALTHY_UI_ID_AFTER" == "$HEALTHY_UI_ID_BEFORE" ]]' in runtime
    assert "healthy_openwebui_container_was_recreated" in runtime
    assert "OPEN_WEBUI_REUSE=PASS" in runtime


def test_job_timeout_has_safe_headroom_above_nested_runtime_budgets():
    launcher = JOB_RUNTIME.read_text()
    runtime = RUNTIME.read_text()
    assert 'env LIFEOS_RUNTIME_JOB_ID="$JOB_ID" "$RUNTIME"' in launcher
    assert 'timeout "$TIMEOUT_SECONDS" "$DEPLOY"' in runtime
    assert 'timeout 30 docker exec "$HA_CONTAINER"' in runtime
    assert 'timeout 180 docker exec "$HA_CONTAINER"' in runtime
    assert 'timeout 120 docker restart "$HA_CONTAINER"' in runtime
    assert "wait_url http://127.0.0.1:8123/ 180" in runtime
    outer_timeout = int(
        launcher.split("readonly OUTER_TIMEOUT_SECONDS=", 1)[1].splitlines()[0]
    )
    deployment_timeout = int(
        runtime.split("TIMEOUT_SECONDS=", 1)[1].splitlines()[0]
    )
    # Allow every HA bound plus ten minutes for ordinary Docker/systemd work
    # and for signal-triggered restoration of the last-known-good HA config.
    ha_timeout_budget = 180 + 30 + 180 + 120 + 180 + 180 + 15
    assert outer_timeout >= deployment_timeout + ha_timeout_budget + 600


def test_deployment_timeout_covers_all_slow_ui_phases():
    deploy = DEPLOY.read_text()
    runtime = RUNTIME.read_text()
    deployment_timeout = int(
        runtime.split("TIMEOUT_SECONDS=", 1)[1].splitlines()[0]
    )
    existing_readiness = 300
    image_pull = 300
    replacement_readiness = 300
    conversation_smoke = 120
    # Leave a minute for backend readiness and ordinary command overhead.
    minimum_budget = (
        existing_readiness
        + image_pull
        + replacement_readiness
        + conversation_smoke
        + 60
    )
    assert 'wait_for_health OPEN_WEBUI_EXISTING "$UI_HEALTH_URL" 300' in deploy
    assert 'timeout 300 docker pull "$OWUI_IMAGE"' in deploy
    assert 'wait_for_health OPEN_WEBUI "$UI_HEALTH_URL" 300' in deploy
    assert 'curl -fsS --max-time 120' in deploy
    assert deployment_timeout >= minimum_budget
