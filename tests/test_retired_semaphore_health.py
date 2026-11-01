from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_active_control_plane_no_longer_requires_retired_semaphore():
    bridge = (ROOT / "governor/ha_issue_queue_bridge.py").read_text()
    deploy = (ROOT / "scripts/lifeos-deploy-ha-control-bridge-impl.sh").read_text()
    dashboard = (ROOT / "scripts/lifeos-adapt-ha-lifeos-dashboard.sh").read_text()

    assert "def semaphore_health" not in bridge
    assert "lifeos-semaphore-shadow-semaphore-1" not in bridge
    assert 'degraded.append("semaphore")' not in bridge
    assert '"semaphore": semaphore' not in bridge
    assert "'state','github_runner','semaphore'" not in deploy
    assert "state_attr('sensor.lifeos_control_state','semaphore')" not in dashboard


def test_current_engineer_backend_remains_protected():
    bridge = (ROOT / "governor/ha_issue_queue_bridge.py").read_text()
    assert '"lifeos-engineer.service"' in bridge
    assert '"lifeos-control-job-submit.socket"' in bridge
