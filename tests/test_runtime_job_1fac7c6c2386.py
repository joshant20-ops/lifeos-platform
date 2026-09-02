from pathlib import Path


LAUNCHER = Path("governor/runtime_jobs/1fac7c6c2386.sh")


def test_launcher_is_bounded_idempotent_and_uses_automatic_classification():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert "timeout --signal=TERM --kill-after=5s 50s python3" in text
    assert 'job.get("request") == request_text' in text
    submit_line = next(line for line in text.splitlines() if 'call("/jobs?async=1"' in line)
    assert submit_line.strip() == 'job = call("/jobs?async=1", {"request": request_text})'


def test_launcher_covers_acceptance_and_sensitive_regression_control():
    text = LAUNCHER.read_text()
    for marker in (
        'source.classify_privacy(request_text) != "normal"',
        'live.classify_privacy(request_text) != "normal"',
        'source.classify_privacy(text) != "local-only"',
        'live.classify_privacy(text) != "local-only"',
        'job.get("privacy") != "normal"',
        '"BUILDER_ROUTE=normal"',
        '"cloud_builder_forbidden_for_local_only_job"',
        '"PUBLICATION_EVIDENCE:"',
        '"PI5_RUNTIME_EVIDENCE:"',
        'verdict.get("verdict") not in {"PASS", "FAIL"}',
        '"Elapsed:"',
        '"ETA estimate"',
    ):
        assert marker in text


def test_launcher_emits_required_machine_contracts():
    text = LAUNCHER.read_text()
    for key in (
        "ISSUE_VALIDITY=", "LIFEOS_WORK_STATE=", "BARRIER=",
        "NEXT_AUTONOMOUS_ACTION=", "DISCOVERED_ISSUES_JSON_B64=",
        "RESULT=", "TESTS=", "NEXT_RUNTIME_CHECK=",
    ):
        assert key in text
