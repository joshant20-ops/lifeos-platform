from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/37cd9ca5d07f.sh"


def test_launcher_is_bounded_pi5_job_using_authorised_broker_path():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -Eeuo pipefail" in text
    assert '[[ "$(hostname)" == Docker ]]' in text
    assert "timeout --signal=TERM --kill-after=10s" in text
    assert "governor/runtime_jobs/16101567d458.sh" in text
    assert "sudo" not in text
    assert "ssh " not in text


def test_launcher_pins_deployment_and_complete_historical_acceptance():
    text = LAUNCHER.read_text()
    required = (
        "6968eb4ea119f371a49960630cc7a4e62a094943",
        "fd7b1ce6e89bfd195fd86cb03a39f3c0ad592dc04d2091232f027f28375e23e7",
        "MAX_SOURCE_AGE",
        "MAX_SOURCE_TIMESTAMP_DELTA",
        "CROSSCHECK_REQUIRED_GOOD_RUNS",
        "EVENT_5833_PRE_EVENT_PROOF=PASS",
        "EVENT_5833_ACTIVE_PROOF=PASS",
        "EVENT_5833_RESTORE_PROOF=PASS",
        "CONTROLLER_OWNERSHIP_CLEARED=PASS",
        "ISSUE_VALIDITY=",
        "LIFEOS_WORK_STATE=",
        "DISCOVERED_ISSUES_JSON_B64=none",
        "RESULT=",
        "NEXT_RUNTIME_CHECK=",
    )
    for value in required:
        assert value in text


def test_launcher_never_replays_the_expired_controller_event():
    text = LAUNCHER.read_text()
    assert "systemctl start --wait lifeos-powerdown-assurance-active.service" not in text
    assert "event proof is not ordered" in text
    assert 'final_control.get("write_performed") is False' in text
