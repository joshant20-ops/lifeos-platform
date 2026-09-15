import pathlib
import subprocess
import sys
import tempfile
import unittest


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


def repositories(root):
    remote = root / "remote.git"
    seed = root / "seed"
    pi = root / "pi"
    run("git", "init", "--bare", str(remote))
    run("git", "symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
    run("git", "init", "-b", "main", str(seed))
    run("git", "remote", "add", "origin", str(remote), cwd=seed)
    commit(seed, "base", "base\n")
    run("git", "push", "-u", "origin", "main", cwd=seed)
    run("git", "clone", str(remote), str(pi))
    return remote, seed, pi


class CanonicalCheckoutReconcileTests(unittest.TestCase):
    def test_reconciles_clean_divergent_commits_with_identical_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            _, seed, pi = repositories(pathlib.Path(directory))
            commit(seed, "canonical copy", "same\n")
            run("git", "push", "origin", "main", cwd=seed)
            commit(pi, "pi copy", "same\n")

            result = run(sys.executable, str(SCRIPT), str(pi), check=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CANONICAL_RECONCILE=identical_tree_ref_converged", result.stdout)
            self.assertEqual(
                run("git", "rev-parse", "HEAD", cwd=pi).stdout,
                run("git", "rev-parse", "origin/main", cwd=pi).stdout,
            )
            self.assertEqual(run("git", "status", "--porcelain", cwd=pi).stdout, "")

    def test_reconciles_when_local_tree_exists_in_canonical_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            _, seed, pi = repositories(pathlib.Path(directory))
            commit(seed, "canonical equivalent", "same\n")
            run("git", "push", "origin", "main", cwd=seed)
            commit(pi, "pi equivalent", "same\n")
            (seed / "canonical-only.txt").write_text("later canonical hardening\n")
            run("git", "add", "canonical-only.txt", cwd=seed)
            run(
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "-m", "later canonical hardening", cwd=seed,
            )
            run("git", "push", "origin", "main", cwd=seed)

            result = run(sys.executable, str(SCRIPT), str(pi), check=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CANONICAL_RECONCILE=canonical_tree_lineage_converged", result.stdout)
            self.assertEqual(
                run("git", "rev-parse", "HEAD", cwd=pi).stdout,
                run("git", "rev-parse", "origin/main", cwd=pi).stdout,
            )
            self.assertEqual((pi / "canonical-only.txt").read_text(), "later canonical hardening\n")

    def test_canonical_blob_can_bootstrap_reconcile_before_helper_exists_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            _, seed, pi = repositories(pathlib.Path(directory))
            commit(seed, "canonical copy", "same\n")
            run("git", "push", "origin", "main", cwd=seed)
            commit(pi, "pi copy", "same\n")
            script = SCRIPT.read_text()

            result = subprocess.run(
                [sys.executable, "-", str(pi)],
                input=script,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CANONICAL_RECONCILE=identical_tree_ref_converged", result.stdout)
            self.assertEqual(
                run("git", "rev-parse", "HEAD", cwd=pi).stdout,
                run("git", "rev-parse", "origin/main", cwd=pi).stdout,
            )

    def test_rejects_clean_divergent_commits_with_different_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            _, seed, pi = repositories(pathlib.Path(directory))
            commit(seed, "canonical change", "canonical\n")
            run("git", "push", "origin", "main", cwd=seed)
            commit(pi, "different pi change", "different\n")
            before = run("git", "rev-parse", "HEAD", cwd=pi).stdout

            result = run(sys.executable, str(SCRIPT), str(pi), check=False)

            self.assertEqual(result.returncode, 20)
            self.assertIn("CANONICAL_CHECKOUT_NOT_READY=non_fast_forward", result.stderr)
            self.assertEqual(run("git", "rev-parse", "HEAD", cwd=pi).stdout, before)

    def test_rejects_dirty_checkout_without_changing_head(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, pi = repositories(pathlib.Path(directory))
            before = run("git", "rev-parse", "HEAD", cwd=pi).stdout
            (pi / "untracked.txt").write_text("keep me\n")

            result = run(sys.executable, str(SCRIPT), str(pi), check=False)

            self.assertEqual(result.returncode, 20)
            self.assertIn("CANONICAL_CHECKOUT_NOT_READY=dirty", result.stderr)
            self.assertEqual((pi / "untracked.txt").read_text(), "keep me\n")
            self.assertEqual(run("git", "rev-parse", "HEAD", cwd=pi).stdout, before)


if __name__ == "__main__":
    unittest.main()
