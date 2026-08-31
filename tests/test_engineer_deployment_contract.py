import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "governor/scripts/deploy-engineer-ai.sh"
RUNTIME = ROOT / "governor/runtime_jobs/ebf8a71d4bff.sh"


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
    reuse = script.index("OPEN_WEBUI_REUSED=healthy_existing_container")
    removal = script.index('docker rm -f "$UI_NAME"')
    assert reuse < removal
    assert "RECREATE_UI=false" in script[reuse:removal]


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


def test_runtime_discovers_real_lan_address_and_nonstandard_ha_container():
    runtime = RUNTIME.read_text()
    assert "ip -4 route get 192.168.0.201" in runtime
    assert "pi5_lan_address_not_found" in runtime
    assert "{{.Names}}|{{.Ports}}" in runtime
    assert "8123->8123\\/tcp" in runtime
    assert "HA_CONTAINER=$(discover_ha_container)" in runtime
