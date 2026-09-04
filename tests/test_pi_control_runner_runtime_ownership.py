from pathlib import Path

RUNNER = Path('homelab/live/usr/local/sbin/lifeos-pi-control-runner').read_text()


def test_runner_protects_all_runtime_owned_paths_from_git_sync():
    for token in (
        'jobs/staging', 'jobs/staged', 'jobs/pending', 'jobs/archive',
        'jobs/scripts', 'jobs/change-scripts', 'jobs/root-scripts', 'results', 'state',
    ):
        assert token in RUNNER
    assert 'RUNTIME_SPECS' in RUNNER
    assert '--no-write-fetch-head' in RUNNER
    assert '+refs/heads/main:refs/remotes/origin/main' in RUNNER
    assert 'fetch unexpectedly changed checked-out HEAD' in RUNNER


def test_runner_does_not_publish_runtime_state_back_to_git():
    forbidden = (
        'git(\n        "add"',
        '"commit",\n            "-m"',
        'git("rebase"',
        'git("push"',
    )
    for token in forbidden:
        assert token not in RUNNER
    assert '"persistence": "local-runtime"' in RUNNER
    assert 'Result persisted locally' in RUNNER


def test_runner_preserves_existing_execution_safety_gates():
    for token in (
        'Another control runner is active',
        'script checksum mismatch',
        'manifest failed Gitleaks',
        'script failed Gitleaks',
        'V3 pre-change baseline failed',
        'critical pre-change health failed',
        'root broker unavailable',
        'job already completed',
        'job already archived',
        'QUEUE PAUSED',
    ):
        assert token in RUNNER
