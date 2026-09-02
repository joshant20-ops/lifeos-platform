from pathlib import Path


SCRIPT = Path("governor/runtime_jobs/a56ef2e00b48.sh")


def test_launcher_is_single_bounded_pi5_entrypoint_and_read_only_by_default():
    text = SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    assert "timeout --signal=TERM --kill-after=15s 900s ssh" in text
    assert "TowerPC.Tailor" in text
    assert "YES-I-APPROVE-Z97-R580" in text
    assert "production_change=NOT_RUN" in text
    assert text.index("explicit approval absent") < text.index("apt-get --no-install-recommends install ${remove_args[*]}")


def test_launcher_proves_issue_7_acceptance_contract():
    text = SCRIPT.read_text()
    for marker in (
        "nvidia-driver-580=$version",
        "nvidia-dkms-580",
        "nvidia-kernel-source-580",
        "version 59[05]*",
        "version 6[01]0*",
        "R580_DEPENDENCY_GRAPH=",
        "TRANSACTION_INSTALL=",
        "TRANSACTION_REMOVE=",
        "critical_removals=none",
        "/usr/src/linux-headers-$kernel",
        "rollback_kernel=",
        "Ollama remains loopback-only",
    ):
        assert marker in text


def test_launcher_emits_machine_contract_on_success_and_failure():
    text = SCRIPT.read_text()
    for key in (
        "ISSUE_VALIDITY=", "LIFEOS_WORK_STATE=", "BARRIER=",
        "NEXT_AUTONOMOUS_ACTION=", "DISCOVERED_ISSUES_JSON_B64=",
        "RESULT=", "TESTS=", "NEXT_RUNTIME_CHECK=",
    ):
        assert key in text
    assert 'command=%q' in text
