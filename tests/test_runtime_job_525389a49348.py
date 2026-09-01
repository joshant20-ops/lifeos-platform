from pathlib import Path


SCRIPT = Path("governor/runtime_jobs/525389a49348.sh").read_text()


def test_runtime_launcher_is_single_identity_aware_resume_path():
    assert "PUBLISHER_EXECUTION_CONTRACT" in SCRIPT
    assert "runuser probe intentionally not attempted" in SCRIPT
    assert "activate-engineer-v1-660a6d4862fa" in SCRIPT
    assert "existing_accepted_job_missing" in SCRIPT
    assert "submit-control-job" not in SCRIPT


def test_connectivity_failures_are_distinct_and_use_clean_git_context():
    assert "FAIL=dns_resolution" in SCRIPT
    assert "class=ssh_authentication" in SCRIPT
    assert "class=git_remote" in SCRIPT
    assert "env -i HOME=/home/joshan" in SCRIPT
    assert "git -C \"$CONTROL\" ls-remote origin refs/heads/main" in SCRIPT
    assert "StrictHostKeyChecking=no" not in SCRIPT


def test_activation_is_checksum_pinned_and_never_overwrites_live_directly():
    assert "EXPECTED_SHA=c17e686746a932d87996eb9cb375f5076603b5a618250853f4f007d81db284bc" in SCRIPT
    assert "existing checksum-pinned protected activation path" in SCRIPT
    assert "install " not in SCRIPT
    assert "cp " not in SCRIPT
    assert "mv " not in SCRIPT


def test_publisher_failure_is_not_ignored():
    assert 'run 180s "$PUBLISHER" || fail publisher_failed_closed' in SCRIPT
