from pathlib import Path


SCRIPT = Path("governor/runtime_jobs/2749620a3364.sh").read_text()


def test_launcher_is_read_only_bounded_and_emits_required_evidence():
    assert SCRIPT.startswith("#!/usr/bin/env bash\n")
    assert "timeout --signal=TERM --kill-after=5s" in SCRIPT
    assert "systemctl start" not in SCRIPT
    assert "gh issue edit" not in SCRIPT
    assert "gh issue comment" not in SCRIPT
    assert "PRODUCTION_R580" not in SCRIPT
    for marker in (
        "ISSUE_JOB_EVIDENCE_JSON=", "obsolete_bootstrap_excluded", "production_r580_change_executed",
        "ISSUE_VALIDITY=", "LIFEOS_WORK_STATE=", "BARRIER=", "NEXT_AUTONOMOUS_ACTION=",
        "DISCOVERED_ISSUES_JSON_B64=", "RESULT=", "TESTS=", "NEXT_RUNTIME_CHECK=",
    ):
        assert marker in SCRIPT


def test_launcher_checks_current_pipeline_services_and_persisted_link():
    for contract in (
        "lifeos-backlog-runner.timer", "lifeos-autonomous-agent.service", "lifeos-job-publisher.service", "/jobs",
        "gh issue view", "state.json", "governor/job_records", "Process GitHub issue #7 ",
    ):
        assert contract in SCRIPT
