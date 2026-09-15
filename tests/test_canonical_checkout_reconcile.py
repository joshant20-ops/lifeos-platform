import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile-canonical-checkout.py"


def run(*args, cwd=None, check=True):
    return subprocess.run(
        list(args), cwd=cwd, check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def commit(repo, message, content):
    (repo / "value.txt").write_text(content)
    run("git", "add", "value.txt", cwd=repo)
    run("git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-m", message, cwd=repo)


def repositories(tmp_path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    pi = tmp_path / "pi"
    run("git", "init", "--bare", str(remote))
    run("git", "init", "-b", "main", str(seed))
    run("git", "remote", "add", "origin", str(remote), cwd=seed)
    commit(seed, "base", "base\n")
    run("git", "push", "-u", "origin", "main", cwd=seed)
    run("git", "clone", str(remote), str(pi))
    return remote, seed, pi


def test_reconciles_clean_divergent_commits_with_identical_trees(tmp_path):
    _, seed, pi = repositories(tmp_path)
    commit(seed, "canonical copy", "same\n")
    run("git", "push", "origin", "main", cwd=seed)
    commit(pi, "pi copy", "same\n")

    result = run(sys.executable, str(SCRIPT), str(pi), check=False)

    assert result.returncode == 0, result.stderr
    assert "CANONICAL_RECONCILE=identical_tree_ref_converged" in result.stdout
    assert run("git", "rev-parse", "HEAD", cwd=pi).stdout == run(
        "git", "rev-parse", "origin/main", cwd=pi
    ).stdout
    assert run("git", "status", "--porcelain", cwd=pi).stdout == ""


def test_rejects_clean_divergent_commits_with_different_trees(tmp_path):
    _, seed, pi = repositories(tmp_path)
    commit(seed, "canonical change", "canonical\n")
    run("git", "push", "origin", "main", cwd=seed)
    commit(pi, "different pi change", "different\n")
    before = run("git", "rev-parse", "HEAD", cwd=pi).stdout

    result = run(sys.executable, str(SCRIPT), str(pi), check=False)

    assert result.returncode == 20
    assert "CANONICAL_CHECKOUT_NOT_READY=non_fast_forward" in result.stderr
    assert run("git", "rev-parse", "HEAD", cwd=pi).stdout == before


def test_rejects_dirty_checkout_without_changing_head(tmp_path):
    _, _, pi = repositories(tmp_path)
    before = run("git", "rev-parse", "HEAD", cwd=pi).stdout
    (pi / "untracked.txt").write_text("keep me\n")

    result = run(sys.executable, str(SCRIPT), str(pi), check=False)

    assert result.returncode == 20
    assert "CANONICAL_CHECKOUT_NOT_READY=dirty" in result.stderr
    assert (pi / "untracked.txt").read_text() == "keep me\n"
    assert run("git", "rev-parse", "HEAD", cwd=pi).stdout == before
