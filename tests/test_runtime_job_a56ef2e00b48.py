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
        "version 6*",
        "R580_DEPENDENCY_GRAPH=",
        "TRANSACTION_INSTALL=",
        "TRANSACTION_REMOVE=",
        "critical_removals=none",
        "critical='^(proxmox|pve-",
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
    assert 'printf "STAGE=%s FAIL rc=%s line=%s command=%q\\nBARRIER=%s\\n"' in text
    assert "sed -n 's/^BARRIER=//p'" in text
    assert 'fail "$barrier"' in text


def test_metadata_refresh_isolated_from_unrelated_host_sources():
    text = SCRIPT.read_text()
    assert "find /var/lib/apt/lists -maxdepth 1 -type f -readable" in text
    assert '-exec cp -- {} "$w/state/lists/"' in text
    assert 'cp -a /var/lib/apt/lists/.' not in text
    assert ': >"$w/etc/apt/sources.list"' in text
    assert "Debug::NoLocking=1" in text
    assert 'APT::Sandbox::User=$(id -un)' in text
    assert 'cp -a /etc/apt/sources.list.d/.' not in text


def test_simulation_uses_only_disposable_writable_apt_state():
    text = SCRIPT.read_text()
    assert 'cp -- /var/lib/dpkg/status "$w/state/status"' in text
    assert 'cp -- /var/lib/apt/extended_states "$w/state/extended_states"' in text
    assert 'Dir::State::status=/var/lib/dpkg/status' not in text
    for option in (
        'Dir::State=$w/state',
        'Dir::State::status=$w/state/status',
        'Dir::State::extended_states=$w/state/extended_states',
        'Dir::State::lists=$w/state/lists',
        'Dir::Cache=$w/cache',
        'Dir::Log=$w/log',
    ):
        assert option in text


def test_metadata_failure_keeps_full_diagnostics_for_watchman():
    text = SCRIPT.read_text()
    assert 'metadata_log="$w/metadata-update.txt"' in text
    assert 'apt-get "${o[@]}" update >"$metadata_log" 2>&1' in text
    assert 'cat "$metadata_log" >&2' in text


def test_every_simulated_removal_must_belong_to_the_old_gpu_inventory():
    text = SCRIPT.read_text()
    assert "unexpected_removals=$(comm -13" in text
    assert "[[ -z $unexpected_removals ]]" in text
    assert "REFUSED: removal set drift" in text
    assert "exit 24" in text


def test_remote_evidence_is_persisted_before_failure_dispatch():
    text = SCRIPT.read_text()
    copy = text.index('cp "$tmp/remote" "$EVIDENCE"')
    failure = text.index('if [[ $rc -ne 0 ]]')
    assert copy < failure
    assert "REMOTE_EVIDENCE=%s" in text
