import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "governor/scripts/deploy-engineer-ai.sh"
BACKEND = ROOT / "governor/engineer_backend.py"


def test_engineer_backend_exposes_health_readiness_endpoint():
    backend = BACKEND.read_text()
    assert 'path = urllib.parse.urlparse(self.path).path' in backend
    assert 'if path in ("/health", "/v1/health"):' in backend
    assert 'if agent.get("status") != "ok":' in backend
    assert 'raise RuntimeError("agent_not_ready")' in backend
    assert 'self.send_json(200, {"service": "lifeos-engineer", "status": "ok"' in backend
    assert 'self.send_json(503, {"service": "lifeos-engineer", "status": "degraded"' in backend


def test_engineer_verification_is_backend_only():
    assert os.access(DEPLOY, os.X_OK)
    script = DEPLOY.read_text()
    assert "lifeos-engineer.service" in script
    assert "http://127.0.0.1:${BACKEND_PORT}/health" in script
    assert "/v1/models" in script
    assert "/v1/chat/completions" in script
    assert "OPENWEBUI=RETIRED" in script
    assert "docker run" not in script
    assert "docker pull" not in script
    assert "lifeos-engineer-ui" not in script
    assert "open-webui/open-webui" not in script


def test_backend_verification_keeps_failure_diagnostics():
    script = DEPLOY.read_text()
    assert "journalctl -u lifeos-engineer.service -n 200" in script
    assert "DEPLOYMENT_FAILURE=unexpected phase=%s line=%s exit=%s" in script
    assert "trap 'unexpected_failure \"$LINENO\"' ERR" in script
    assert "wait_for_health ENGINEER_BACKEND" in script


def test_openwebui_is_not_desired_compose_runtime():
    projects = (ROOT / "ansible/vars/compose_projects.json").read_text()
    managed = (ROOT / "homelab/.managed-files.txt").read_text()
    assert '"project": "lifeos-engineer-ui"' not in projects
    assert "opt/stacks/lifeos-engineer-ui/docker-compose.yml" not in managed
