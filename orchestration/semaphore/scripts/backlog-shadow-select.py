#!/usr/bin/env python3
"""Pure, read-only LifeOS backlog selection for Semaphore shadow comparison."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CENTRAL_ISSUE = 24
MANUAL_HIGH_PRIORITY_LABEL = "lifeos-high-priority"


def labels(issue):
    return {str(x.get("name", "")).lower() for x in issue.get("labels", [])}


def priority(issue):
    title, ls = issue.get("title", ""), labels(issue)
    manual_tier = 0 if MANUAL_HIGH_PRIORITY_LABEL in ls else 1
    rank = next(
        (
            n
            for n in range(6)
            if re.match(rf"^P{n}\b", title, re.I)
            or f"priority:p{n}" in ls
            or f"p{n}" in ls
        ),
        6,
    ) * 100
    if "lifeos-engineer-ready" in ls:
        rank -= 25
    return manual_tier, rank, issue.get("created_at", ""), int(issue["number"])


def eligible(issue, state, timestamp):
    number = int(issue["number"])
    ls = labels(issue)
    if number == CENTRAL_ISSUE or ls & {"lifeos-engineer-ignore", "do-not-automate"}:
        return False
    if ls & {"blocked", "waiting-human", "waiting-dependency"}:
        return False
    entry = state.get("issues", {}).get(str(number), {})
    if entry.get("work_state") == "PASS":
        return False
    retry_after = entry.get("retry_after")
    return not retry_after or int(retry_after) <= int(timestamp)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: backlog-shadow-select.py SNAPSHOT.json")
    data = json.loads(Path(sys.argv[1]).read_text())
    issues = data.get("issues", [])
    state = data.get("state", {})
    timestamp = int(data["timestamp"])
    candidates = [i for i in issues if eligible(i, state, timestamp)]
    chosen = sorted(candidates, key=priority)[0] if candidates else None
    result = {
        "selected_issue": int(chosen["number"]) if chosen else None,
        "candidate_count": len(candidates),
        "timestamp": timestamp,
    }
    print(json.dumps(result, sort_keys=True))
    selected = result["selected_issue"] if result["selected_issue"] is not None else "none"
    print(
        f"LIFEOS_SEMAPHORE_BACKLOG_SHADOW=PASS selected_issue={selected} "
        f"candidate_count={result['candidate_count']} mutation=none"
    )


if __name__ == "__main__":
    main()
