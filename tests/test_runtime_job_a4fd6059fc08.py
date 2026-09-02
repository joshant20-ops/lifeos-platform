from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/a4fd6059fc08.sh"
DELEGATE = ROOT / "governor/runtime_jobs/a181c9270e39.sh"


def test_job_launcher_is_bounded_watchman_entrypoint():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert '[[ "$(hostname)" == Docker ]]' in text
    assert '[[ "$(id -u)" -eq 0 ]]' in text
    assert "timeout --signal=TERM --kill-after=10s 300s" in text
    assert "sudo" not in text
    assert "ssh " not in text


def test_job_launcher_pins_reviewed_post_event_verifier():
    import hashlib

    text = LAUNCHER.read_text()
    digest = hashlib.sha256(DELEGATE.read_bytes()).hexdigest()
    assert f"readonly DELEGATE_SHA={digest}" in text
    assert 'exec timeout --signal=TERM --kill-after=10s 300s "$DELEGATE"' in text


def test_delegate_requires_complete_issue_25_runtime_proof():
    text = DELEGATE.read_text()
    for evidence in (
        "6968eb4ea119f371a49960630cc7a4e62a094943",
        "canonical_commit_scope_mismatch",
        "PROTECTED_DEPLOYMENT=PASS",
        "controller_run_one_failed",
        "controller_run_two_failed",
        "EVENT_5833_PRE_EVENT_PROOF=PASS",
        "EVENT_5833_ACTIVE_PROOF=PASS",
        "EVENT_5833_RESTORE_PROOF=PASS",
        "CONTROLLER_OWNERSHIP_CLEARED=PASS",
        "ISSUE_VALIDITY=ALREADY_COMPLETE",
        "LIFEOS_WORK_STATE=PASS",
    ):
        assert evidence in text
