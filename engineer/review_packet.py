#!/usr/bin/env python3
"""Generate a compact, provider-independent daily senior-review packet."""
import argparse, json, subprocess
from datetime import datetime, timezone
from pathlib import Path

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20).stdout.strip()

def build(repo: Path) -> dict:
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "purpose": "daily-senior-review",
            "provider_role": "codex-senior-review", "head": git(repo, "rev-parse", "HEAD"),
            "branch": git(repo, "branch", "--show-current"), "recent_commits": git(repo, "log", "-5", "--pretty=%h %s").splitlines(),
            "changed_paths": git(repo, "status", "--short").splitlines()[:100],
            "diff_stat": git(repo, "diff", "--stat")[:4000], "content_included": False}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--repo", type=Path, required=True)
    print(json.dumps(build(parser.parse_args().repo), sort_keys=True))
