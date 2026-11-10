from pathlib import Path
import re
def test_actual_is_local_persistent_and_restartable():
    s=Path("ansible/desired/compose/actual-budget/docker-compose.yml").read_text()
    assert "actualbudget/actual-server:latest-alpine" in s
    assert "/opt/stacks/actual-budget/data:/data" in s
    assert '"127.0.0.1:5006:5006"' in s
    assert "restart: unless-stopped" in s
def test_deploy_has_runtime_acceptance():
    s=Path("scripts/deploy-actual-budget.sh").read_text()
    assert "curl -fsS http://127.0.0.1:5006/" in s
    assert "docker compose up -d" in s
