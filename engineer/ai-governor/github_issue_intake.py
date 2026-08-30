#!/usr/bin/env python3
"""Ingest explicitly eligible GitHub issues into the LifeOS AI governor queue.

The intake is deliberately narrow and idempotent.  An issue is eligible only when
its body contains the ready marker or it carries the configured ready label.
Pull requests are ignored.  The queue lives in the governor state directory and
uses stable GitHub issue IDs, so repeated polling cannot enqueue duplicates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = os.environ.get("LIFEOS_GITHUB_REPOSITORY", "joshant20-ops/lifeos-platform")
DEFAULT_BRANCH = os.environ.get("LIFEOS_GITHUB_BASE_BRANCH", "main")
DEFAULT_READY_LABEL = os.environ.get("LIFEOS_GITHUB_READY_LABEL", "lifeos-engineer-ready")
DEFAULT_READY_MARKER = os.environ.get("LIFEOS_GITHUB_READY_MARKER", "<!-- lifeos-engineer:ready -->")
DEFAULT_STATE_DIR = Path(os.environ.get("LIFEOS_GOVERNOR_STATE_DIR", Path.home() / ".local/state/lifeos-ai-governor"))
API_ROOT = "https://api.github.com"
MAX_ISSUE_BODY = 64 * 1024
RISKS = {"TINY", "NORMAL", "HIGH_RISK", "SENIOR_REVIEW"}
DEFAULT_ACCEPTANCE = [
    "python3 -m pytest engineer/ai-governor/tests",
    "python3 -m compileall -q engineer",
    "git diff --check",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def token() -> str:
    value = os.environ.get("LIFEOS_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not value:
        raise RuntimeError("LIFEOS_GITHUB_TOKEN or GITHUB_TOKEN is required")
    return value


def api_get(path: str) -> Any:
    if not path.startswith("/"):
        raise ValueError("GitHub API path must be absolute")
    request = urllib.request.Request(
        API_ROOT + path,
        headers={
            "Authorization": f"Bearer {token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lifeos-ai-governor-github-intake/1",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def atomic_create_json(path: Path, value: Any) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def labels(issue: dict[str, Any]) -> set[str]:
    result = set()
    for item in issue.get("labels") or []:
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, dict) and item.get("name"):
            result.add(str(item["name"]))
    return result


def eligible(issue: dict[str, Any], ready_label: str, ready_marker: str) -> bool:
    if "pull_request" in issue:
        return False
    body = str(issue.get("body") or "")
    return ready_marker in body or ready_label in labels(issue)


def risk_for(issue: dict[str, Any]) -> str:
    mapping = {
        "risk:tiny": "TINY",
        "risk:normal": "NORMAL",
        "risk:high": "HIGH_RISK",
        "risk:senior": "SENIOR_REVIEW",
    }
    issue_labels = labels(issue)
    for label, risk in mapping.items():
        if label in issue_labels:
            return risk
    body = str(issue.get("body") or "")
    match = re.search(r"<!--\s*lifeos-risk:(TINY|NORMAL|HIGH_RISK|SENIOR_REVIEW)\s*-->", body)
    return match.group(1) if match else "NORMAL"


def comment_values(body: str, name: str) -> list[str]:
    pattern = rf"<!--\s*{re.escape(name)}:(.*?)\s*-->"
    return [match.strip() for match in re.findall(pattern, body) if match.strip()]


def base_commit(repository: str, branch: str) -> str:
    encoded = urllib.parse.quote(branch, safe="")
    data = api_get(f"/repos/{repository}/commits/{encoded}")
    sha = str(data.get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("GitHub did not return a valid base commit")
    return sha


def build_job(issue: dict[str, Any], repository: str, branch: str, commit: str) -> dict[str, Any]:
    number = int(issue["number"])
    body = str(issue.get("body") or "")[:MAX_ISSUE_BODY]
    title = str(issue.get("title") or "").strip()
    url = str(issue.get("html_url") or f"https://github.com/{repository}/issues/{number}")
    context_paths = comment_values(body, "lifeos-context")
    acceptance = comment_values(body, "lifeos-accept") or list(DEFAULT_ACCEPTANCE)
    risk = risk_for(issue)
    if risk not in RISKS:
        risk = "NORMAL"
    task = (
        f"GitHub issue #{number}: {title}\n\n"
        f"Source: {url}\nRepository: {repository}\nBase branch: {branch}\n\n"
        f"{body}"
    )
    return {
        "id": f"github-{repository.replace('/', '-')}-issue-{number}",
        "task": task,
        "risk": risk,
        "deterministic_available": False,
        "substantial": risk != "TINY",
        "requires_review": risk != "TINY",
        "base_commit": commit,
        "context_paths": context_paths,
        "acceptance_commands": acceptance,
    }


def list_open_issues(repository: str) -> list[dict[str, Any]]:
    data = api_get(f"/repos/{repository}/issues?state=open&sort=created&direction=asc&per_page=100")
    if not isinstance(data, list):
        raise RuntimeError("GitHub issues response was not a list")
    return data


def ingest(repository: str, branch: str, state_dir: Path, ready_label: str, ready_marker: str,
           dry_run: bool = False) -> dict[str, Any]:
    pending = state_dir / "queue" / "pending"
    source_dir = state_dir / "queue" / "sources"
    selected = [issue for issue in list_open_issues(repository) if eligible(issue, ready_label, ready_marker)]
    commit = base_commit(repository, branch) if selected else None
    queued = []
    duplicates = []
    for issue in selected:
        job = build_job(issue, repository, branch, str(commit))
        number = int(issue["number"])
        job_path = pending / f"{job['id']}.json"
        source = {
            "schema": "lifeos.github_issue_source.v1",
            "repository": repository,
            "issue_number": number,
            "issue_url": issue.get("html_url"),
            "issue_updated_at": issue.get("updated_at"),
            "queued_at": now(),
            "job_id": job["id"],
        }
        if dry_run:
            queued.append({"issue": number, "job_id": job["id"], "dry_run": True})
            continue
        created = atomic_create_json(job_path, job)
        if created:
            atomic_create_json(source_dir / f"{job['id']}.json", source)
            queued.append({"issue": number, "job_id": job["id"]})
        else:
            duplicates.append({"issue": number, "job_id": job["id"]})
    return {
        "schema": "lifeos.github_issue_intake.v1",
        "generated_at": now(),
        "repository": repository,
        "base_branch": branch,
        "eligible": len(selected),
        "queued": queued,
        "duplicates": duplicates,
        "dry_run": dry_run,
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Queue explicitly eligible GitHub issues for the LifeOS AI governor")
    p.add_argument("--repository", default=DEFAULT_REPOSITORY)
    p.add_argument("--branch", default=DEFAULT_BRANCH)
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p.add_argument("--ready-label", default=DEFAULT_READY_LABEL)
    p.add_argument("--ready-marker", default=DEFAULT_READY_MARKER)
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        result = ingest(args.repository, args.branch, args.state_dir, args.ready_label, args.ready_marker, args.dry_run)
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc), "generated_at": now()}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
