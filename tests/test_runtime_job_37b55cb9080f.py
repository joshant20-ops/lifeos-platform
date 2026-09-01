from pathlib import Path


LAUNCHER = Path("governor/runtime_jobs/37b55cb9080f.sh")


def test_launcher_is_single_idempotent_pi5_entrypoint():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert "timeout --signal=TERM --kill-after=5s 40s python3" in text
    assert 'j.get("request") == request_text' in text
    assert 'call("/jobs?async=1", {"request": request_text})' in text
    assert '"dispatch_builder"' not in text.split("call(\"/jobs?async=1\"")[1].split("\n", 1)[0]


def test_launcher_checks_full_acceptance_path_without_private_content():
    text = LAUNCHER.read_text()
    for marker in (
        'job.get("privacy") != "normal"',
        '"BUILDER_ROUTE=normal"',
        '"cloud_builder_forbidden_for_local_only_job"',
        '"PUBLICATION_EVIDENCE:"',
        '"PI5_RUNTIME_EVIDENCE:"',
        'verdict.get("verdict") != "PASS"',
        '"Elapsed:"',
        '"ETA estimate"',
    ):
        assert marker in text
    assert "document contents" in text
    assert "paperless" not in text.lower()


def test_launcher_emits_required_machine_contracts():
    text = LAUNCHER.read_text()
    for key in (
        "ISSUE_VALIDITY=",
        "LIFEOS_WORK_STATE=",
        "BARRIER=",
        "NEXT_AUTONOMOUS_ACTION=",
        "DISCOVERED_ISSUES_JSON_B64=",
        "RESULT=",
        "TESTS=",
        "NEXT_RUNTIME_CHECK=",
    ):
        assert key in text
