from pathlib import Path


SCRIPT = Path("governor/runtime_jobs/e2f43305af1f.sh")


def test_r580_launcher_is_bounded_and_approval_gated():
    text = SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "timeout --signal=TERM --kill-after=15s 720s ssh" in text
    assert "YES-I-APPROVE-Z97-R580" in text
    assert "production_change=NOT_RUN" in text


def test_simulation_models_r535_removal_and_r580_install_atomically():
    text = SCRIPT.read_text()
    assert 'remove_args+=("$package-")' in text
    assert '"${remove_args[@]}" "nvidia-driver-580=$version"' in text
    assert 'stage_fail "r535_removal_missing_$package"' in text
    assert "stage_fail critical_removal" in text


def test_newer_branches_and_open_modules_fail_closed():
    text = SCRIPT.read_text()
    assert "Pin-Priority: -1" in text
    for branch in ("590", "595", "600", "610"):
        assert f"*-{branch}" in text
    assert "stage_fail r590_plus_leak" in text
    assert "stage_fail open_module_leak" in text


def test_candidate_preserves_repository_and_rollback_surfaces():
    text = SCRIPT.read_text()
    assert "/root/lifeos-r580-source-backup" in text
    assert "/root/lifeos-r535-package-inventory.txt" in text
    assert "rollback_kernel_absent" in text
    assert "POST_REBOOT_PLAN=" in text
