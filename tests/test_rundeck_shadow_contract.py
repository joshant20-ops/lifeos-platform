from pathlib import Path


ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / "orchestration/rundeck/docker-compose.yml"
README = ROOT / "orchestration/rundeck/README.md"
EXAMPLE = ROOT / "orchestration/rundeck/runtime.env.example"


def test_shadow_is_pinned_persistent_and_health_checked():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "rundeck/rundeck:6.1.0" in text
    assert "postgres:17.6-bookworm" in text
    assert text.count("restart: unless-stopped") == 2
    assert text.count("healthcheck:") == 2
    assert "rundeck-data:/home/rundeck/server/data" in text
    assert "rundeck-db:/var/lib/postgresql/data" in text


def test_shadow_fails_closed_to_explicit_lan_binding_and_external_secrets():
    text = COMPOSE.read_text(encoding="utf-8")
    assert '${LIFEOS_RUNDECK_BIND_IP:?set an explicit Pi5 LAN address}:4440:4440' in text
    assert "RUNDECK_DATABASE_PASSWORD:?" in text
    assert "RUNDECK_ADMIN_PASSWORD:?" in text
    assert "internal: true" in text
    assert "docker.sock" not in text
    assert "privileged:" not in text
    assert "network_mode: host" not in text
    assert "/var/lib/lifeos-transactions" not in text


def test_only_placeholder_secrets_are_versioned():
    example = EXAMPLE.read_text(encoding="utf-8")
    assert "replace-with-" in example
    assert "192.0.2.10" in example  # RFC 5737 documentation-only address
    assert "/etc/lifeos/rundeck.env" in README.read_text(encoding="utf-8")


def test_migration_is_explicitly_shadow_only_with_rollback():
    text = README.read_text(encoding="utf-8")
    for required in (
        "not authorised",
        "shadow-only",
        "Backup, restore, and rollback",
        "unchanged compatibility\npath",
        "must never receive unrestricted",
    ):
        assert required in text
