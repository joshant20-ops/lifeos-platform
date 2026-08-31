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
    assert "home_assistant_cannot_reach_engineer" in runtime
    assert 'docker logs --tail 200 --timestamps "$HA_CONTAINER"' in runtime
    assert "python3 -m homeassistant --script check_config -c /config || true" in runtime
    assert "(( delay < 16 )) &&" not in runtime


def test_new_ui_exposes_docker_health_from_health_endpoint():
    script = DEPLOY.read_text()
    assert '--health-cmd=' in script
    assert "http://127.0.0.1:8080/health" in script
    assert "--health-start-period=300s" in script
    assert "--health-retries=3" in script
