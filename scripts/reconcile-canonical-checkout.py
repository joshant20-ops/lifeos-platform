#!/usr/bin/env python3
"""Safely reconcile a clean canonical checkout with origin/main."""
from __future__ import annotations

import pathlib
import subprocess
import sys


def git(repo: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )


def reconcile(repo: pathlib.Path) -> str:
    dirty = git(repo, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    if dirty:
        raise RuntimeError("CANONICAL_CHECKOUT_NOT_READY=dirty\n" + dirty)

    git(repo, "fetch", "--prune", "origin", "main")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    origin = git(repo, "rev-parse", "origin/main").stdout.strip()
    result = "already_aligned"

    if head != origin:
        ancestor = git(repo, "merge-base", "--is-ancestor", head, origin, check=False)
        if ancestor.returncode == 0:
            git(repo, "merge", "--ff-only", "origin/main")
            result = "fast_forward"
        else:
            head_tree = git(repo, "rev-parse", f"{head}^{{tree}}").stdout.strip()
            origin_commits = git(repo, "log", "-n", "256", "--format=%H", "origin/main").stdout.splitlines()
            matching_canonical_commit = next(
                (
                    commit
                    for commit in origin_commits
                    if git(repo, "rev-parse", f"{commit}^{{tree}}").stdout.strip() == head_tree
                ),
                None,
            )
            branch = git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
            if not branch or not matching_canonical_commit:
                raise RuntimeError(
                    "CANONICAL_CHECKOUT_NOT_READY=non_fast_forward\n"
                    f"PLATFORM_HEAD={head}\nORIGIN_MAIN={origin}"
                )
            git(repo, "update-ref", f"refs/heads/{branch}", matching_canonical_commit, head)
            if matching_canonical_commit == origin:
                result = "identical_tree_ref_converged"
            else:
                git(repo, "merge", "--ff-only", "origin/main")
                result = "canonical_tree_lineage_converged"

    final_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    final_origin = git(repo, "rev-parse", "origin/main").stdout.strip()
    final_dirty = git(repo, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    if final_dirty or final_head != final_origin:
        raise RuntimeError("CANONICAL_CHECKOUT_NOT_READY=postcondition_failed")

    print(f"PLATFORM_HEAD={final_head}")
    print(f"CANONICAL_RECONCILE={result}")
    print("CANONICAL_CHECKOUT_READY=PASS")
    return result


def main() -> int:
    repo = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/home/joshan/lifeos-platform").resolve()
    try:
        reconcile(repo)
        return 0
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
