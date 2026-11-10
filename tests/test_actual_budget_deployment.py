from pathlib import Path

def test_actual_is_local_hdd_persistent_and_restartable():
    s=Path("ansible/desired/compose/actual-budget/docker-compose.yml").read_text()
    assert "actualbudget/actual-server:latest-alpine" in s
    assert "/mnt/docker-data/actual-budget:/data" in s
    assert "/opt/stacks/actual-budget/data:/data" not in s
    assert '"127.0.0.1:5006:5006"' in s
    assert "restart: unless-stopped" in s

def test_deploy_fails_closed_without_hdd_mount_and_uses_workspace():
    s=Path("scripts/deploy-actual-budget.sh").read_text()
    assert "GITHUB_WORKSPACE" in s
    assert 'mountpoint -q "$data_root"' in s
    assert "/mnt/docker-data" in s
    assert "curl -fsS http://127.0.0.1:5006/" in s
    assert "docker compose up -d" in s
