from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / 'homelab/live/usr/local/sbin/lifeos-job-publisher'


def test_publisher_never_commits_rebases_pushes_or_pulls_runtime_queue_state():
    source = PUBLISHER.read_text()
    for forbidden in ("git('commit'", "git('rebase'", "git('push'", "git('pull'"):
        assert forbidden not in source
    assert "git('merge', '--ff-only', 'refs/remotes/origin/main')" in source
    assert '+refs/heads/main:refs/remotes/origin/main' in source


def test_runtime_owned_roots_are_explicitly_preflighted_before_sync():
    source = PUBLISHER.read_text()
    for path in (
        'jobs/staging', 'jobs/pending', 'jobs/archive', 'jobs/scripts',
        'jobs/change-scripts', 'jobs/root-scripts', 'results', 'state',
    ):
        assert repr(path) in source
    assert 'origin/main tracks runtime-owned paths; migration required before sync' in source


def test_promotion_is_runtime_atomic_and_git_free():
    source = PUBLISHER.read_text()
    assert 'os.link(manifest, dest)' in source
    assert 'manifest.unlink()' in source
