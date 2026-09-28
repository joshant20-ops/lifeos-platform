#!/usr/bin/env python3
"""Deterministically hydrate an explicit GitHub issue task without solution hints."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request

MAX_BODY_CHARS = 12_000
MAX_COMMENT_CHARS = 6_000
MAX_COMMENTS = 20


def render_task(repo: str, issue: dict, comments: list[dict], workspace: str) -> str:
    number = issue["number"]
    title = str(issue.get("title", "")).strip()
    body = str(issue.get("body") or "")[:MAX_BODY_CHARS]
    parts = [
        "Deterministically hydrated task context (authoritative task input; not a diagnosis or solution):",
        f"Repository: {repo}",
        f"Persistent workspace: {workspace}",
        f"Issue: #{number} — {title}",
        "",
        "Issue body:",
        body,
    ]
    selected = comments[:MAX_COMMENTS]
    if selected:
        parts.extend(["", "Issue comments (oldest first):"])
        for index, comment in enumerate(selected, 1):
            author = (comment.get("user") or {}).get("login", "unknown")
            text = str(comment.get("body") or "")[:MAX_COMMENT_CHARS]
            parts.extend([f"", f"Comment {index} by {author}:", text])
    parts.extend([
        "",
        "Independently inspect the repository, diagnose the defect, and complete the engineering task.",
        "The hydrated material supplies only information the task explicitly requires you to retrieve.",
    ])
    return "\n".join(parts).strip() + "\n"


def fetch_json(url: str, token: str):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "lifeos-openhands-task-hydrator",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        parser.error("GITHUB_TOKEN is required")
    base = f"https://api.github.com/repos/{args.repo}"
    issue = fetch_json(f"{base}/issues/{args.issue}", token)
    comments = fetch_json(f"{base}/issues/{args.issue}/comments?per_page={MAX_COMMENTS}", token)
    if "pull_request" in issue:
        raise SystemExit("requested issue is a pull request")
    print(render_task(args.repo, issue, comments, args.workspace), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
