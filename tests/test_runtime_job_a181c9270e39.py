from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/a181c9270e39.sh"


def test_launcher_is_single_bounded_watchman_entrypoint():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -Eeuo pipefail" in text
    assert '[[ "$(hostname)" == Docker ]]' in text
    assert '[[ "$(id -u)" -eq 0 ]]' in text
    assert "timeout --signal=TERM --kill-after=10s" in text
    assert "sudo" not in text
    assert "ssh " not in text
    assert "lifeos-pi-control" not in text


def test_launcher_pins_exact_fix_and_proves_complete_event_lifecycle():
    text = LAUNCHER.read_text()
    required = (
        "6968eb4ea119f371a49960630cc7a4e62a094943",
        "fd7b1ce6e89bfd195fd86cb03a39f3c0ad592dc04d2091232f027f28375e23e7",
        "canonical_commit_scope_mismatch",
        "MAX_SOURCE_AGE",
        "MAX_SOURCE_TIMESTAMP_DELTA",
        "CROSSCHECK_REQUIRED_GOOD_RUNS",
        "systemctl start --wait",
        "EVENT_5833_PRE_EVENT_PROOF=PASS",
        "EVENT_5833_ACTIVE_PROOF=PASS",
        "EVENT_5833_RESTORE_PROOF=PASS",
        "CONTROLLER_OWNERSHIP_CLEARED=PASS",
    )
    for value in required:
        assert value in text


def test_launcher_cannot_claim_success_without_runtime_evidence():
    text = LAUNCHER.read_text()
    assert 'assert pre, "missing pre-event' in text
    assert 'assert active, "missing gated active-event' in text
    assert 'assert restored, "missing post-event' in text
    assert 'final_control.get("write_performed") is False' in text
    assert "ISSUE_VALIDITY=ALREADY_COMPLETE" in text
    assert "LIFEOS_WORK_STATE=PASS" in text
    assert "RESULT=PASS" in text
