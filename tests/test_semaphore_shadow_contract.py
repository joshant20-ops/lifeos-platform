from pathlib import Path


ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / "orchestration/semaphore/docker-compose.yml"
README = ROOT / "orchestration/semaphore/README.md"
LAUNCHER = ROOT / "governor/runtime_jobs/c3751aaff97b.sh"


def test_shadow_is_pinned_arm64_lan_only_and_persistent():
    text = COMPOSE.read_text()
    assert "semaphoreui/semaphore:v2.18.29" in text
    assert text.count("platform: linux/arm64/v8") == 2
    assert "latest" not in text
    assert "${LIFEOS_SEMAPHORE_BIND_IP" in text
    assert "0.0.0.0:3000" not in text
    assert "semaphore-db:/var/lib/postgresql/data" in text
    assert "semaphore-config:/etc/semaphore" in text
    assert "restart: unless-stopped" in text
    assert "internal: true" in text


def test_shadow_has_no_privileged_runtime_surface_or_inline_secrets():
    text = COMPOSE.read_text()
    for forbidden in ("privileged: true", "/var/run/docker.sock", "/root", "/var/lib/lifeos-transactions", "sudo"):
        assert forbidden not in text
    assert "_FILE:" in text
    assert "SEMAPHORE_ADMIN_PASSWORD:" not in text
    assert "SEMAPHORE_ACCESS_KEY_ENCRYPTION:" not in text
    assert text.count("no-new-privileges:true") == 2
    assert text.count("cap_drop: [ALL]") == 2


def test_runtime_acceptance_fails_closed_before_start():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail")
    assert '${LIFEOS_REPO_ROOT:-/home/joshan/lifeos-platform}' in text
    assert "canonical_pi5_checkout_missing" in text
    assert "/opt/lifeos-platform" not in text
    assert "shadow_source_not_tracked" in text
    assert "shadow_source_not_published" in text
    assert "source_commit_unavailable" in text
    assert text.index("shadow_source_not_published") < text.index("missing_root_owned_semaphore_env")
    assert "source_commit=%s" in text
    assert "timeout 300s" in text
    assert "host_not_arm64" in text
    assert "resolved_image_not_arm64" in text
    assert text.index("resolved_image_not_arm64") < text.index('up -d || fail shadow_start_failed')
    assert "semaphore_not_lan_bound" in text
    assert "bind_ip_not_private_lan" in text
    assert "compatibility_path_disturbed" in text
    assert "RESULT=" in text


def test_migration_and_rollback_boundaries_are_documented():
    text = README.read_text()
    for phrase in ("shadow-only", "No emulation", "root-owned", "Backup, restore, and rollback", "#26"):
        assert phrase in text
