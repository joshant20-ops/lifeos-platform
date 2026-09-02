from pathlib import Path


ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/80f20f03755d.sh"


def test_shadow_acceptance_launcher_is_bounded_and_timeout_aware():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "timeout 12m docker compose" in text
    assert "--project-name \"$PROJECT\"" in text
    assert "--env-file \"$ENV_FILE\"" in text
    assert text.count("compose up -d --wait --wait-timeout 600") == 2
    assert "compose up -d --force-recreate --wait --wait-timeout 600" in text
    assert "-v /var/run/docker.sock" not in text
    assert "--privileged" not in text
    assert "sudo" not in text


def test_shadow_acceptance_preserves_the_real_compatibility_path():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "Semaphore was design-only" in text
    assert text.count("systemctl is-enabled lifeos-backlog-runner.timer") >= 2
    assert text.count("systemctl is-active lifeos-backlog-runner.timer") >= 2
    assert text.count("systemctl is-active lifeos-backlog-runner.service") >= 2
    assert text.count("systemctl is-enabled lifeos-backlog-runner.service") >= 2
    assert "compatibility_service_failed_before_shadow_test" in text
    assert "compatibility_service_failed_after_shadow_test" in text
    assert "compatibility_service_runtime_changed" not in text
    assert "SHADOW_EQUIVALENCE=PASS" in text
    assert "compatibility_path=unchanged" in text


def test_shadow_acceptance_checks_boundaries_health_and_persistence():
    text = LAUNCHER.read_text(encoding="utf-8")
    for required in (
        "root:root:600",
        "repository_shadow_contract_failed",
        ".State.Health.Status",
        ".HostConfig.Privileged",
        ".HostConfig.NetworkMode",
        "rundeck_not_bound_to_configured_lan_address",
        "unresolved_rundeck_image_digest",
        "forbidden_host_mount_detected",
        "lifeos_shadow_acceptance",
        "database_persistence_canary_failed",
        "database_backup_restore_rehearsal_failed",
        "shadow_recreate_or_health_failed",
        "rundeck_recovery_restart_failed",
    ):
        assert required in text


def test_retry_repairs_stale_unhealthy_shadow_without_removing_volumes():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "shadow_needs_recreate=false" in text
    assert ".State.Status" in text
    assert ".State.Health.Status" in text
    assert "--force-recreate" in text
    assert "compose down -v" not in text


def test_launcher_emits_governor_and_wrapper_contracts():
    text = LAUNCHER.read_text(encoding="utf-8")
    for field in (
        "ISSUE_VALIDITY=VALID",
        "LIFEOS_WORK_STATE=%s",
        "BARRIER=%s",
        "NEXT_AUTONOMOUS_ACTION=%s",
        "DISCOVERED_ISSUES_JSON_B64=none",
        "RESULT=%s",
        "TESTS=%s",
        "NEXT_RUNTIME_CHECK=%s",
    ):
        assert field in text


def test_failure_evidence_is_bounded_and_does_not_emit_secret_bearing_logs():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "FAIL_EVIDENCE service={{.Service}} state={{.State}} health={{.Health}}" in text
    assert "compose logs" not in text
    assert "docker inspect" in text
