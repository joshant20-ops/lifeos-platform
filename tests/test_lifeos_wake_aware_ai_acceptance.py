from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "scripts" / "lifeos-wake-aware-ai-acceptance.sh"


def test_acceptance_uses_service_availability_and_records_unknown_power():
    script = ACCEPTANCE.read_text()
    assert 'TOWER_SSH_UNAVAILABLE=PASS' in script
    assert 'OLLAMA_UNAVAILABLE=PASS' in script
    assert 'NO_ACTIVE_INFERENCE_WAKE_LEASE=PASS' in script
    assert 'physical_power' in script
    assert '"UNKNOWN"' in script
    assert 'HEALTH_NO_WAKE=PASS' in script
    assert 'PASSIVE_STATUS_AND_MODEL_DISCOVERY_NO_WAKE=PASS' in script


def test_acceptance_never_issues_shutdown_or_requires_physical_off():
    script = ACCEPTANCE.read_text()
    assert 'lifeos/tower/power/set' not in script
    assert 'assert_off' not in script
    assert 'TOWER_OFF_AFTER_ACCEPTANCE' not in script
    assert 'WAKE_AWARE_STABLE_AI_ACCEPTANCE=PASS' in script
