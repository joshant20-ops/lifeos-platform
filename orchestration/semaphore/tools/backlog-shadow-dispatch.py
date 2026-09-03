#!/usr/bin/env python3
"""Pure read-only LifeOS backlog dispatch planner for Semaphore shadow validation."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CENTRAL_ISSUE = 24
MANUAL_HIGH_PRIORITY_LABEL = "lifeos-high-priority"
PRIVATE_LABELS = {
    "risk:local-only", "privacy:local-only", "local-only", "private",
    "private-data", "financial-private", "paperless-private",
}


def labels(issue):
    return {str(x.get("name", "")).lower() for x in issue.get("labels", [])}


def priority(issue):
    title, ls = issue.get("title", ""), labels(issue)
    manual_tier = 0 if MANUAL_HIGH_PRIORITY_LABEL in ls else 1
    rank = next(
        (
            n
            for n in range(6)
            if re.match(rf"^P{n}\\b", title, re.I)
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


def next_target(plan):
    if not isinstance(plan, dict):
        return None
    targets = []
    for milestone in plan.get("milestones", []):
        targets.extend(milestone.get("targets", []))
    passed = {t.get("id") for t in targets if t.get("state") == "PASS"}
    ready = []
    fallback = []
    for target in targets:
        state = target.get("state")
        deps = set(target.get("depends_on") or [])
        if state in {"PLANNED", "READY"} and deps <= passed:
            ready.append(target)
        elif state in {"FAILED", "BLOCKED"}:
            fallback.append(target)
    return ready[0] if ready else (fallback[0] if fallback else None)


def plan(snapshot):
    timestamp = int(snapshot["timestamp"])
    state = snapshot.get("state", {})
    candidates = [i for i in snapshot.get("issues", []) if eligible(i, state, timestamp)]
    issue = sorted(candidates, key=priority)[0] if candidates else None
    if issue is None:
        return {
            "dispatch": "none",
            "candidate_count": 0,
            "issue": None,
            "phase": None,
            "builder": None,
            "target_id": None,
        }

    number = int(issue["number"])
    entry = state.get("issues", {}).get(str(number), {})
    plan_state = entry.get("plan")
    target = next_target(plan_state) if plan_state else None
    if not plan_state:
        phase = "planning"
        target_id = None
    elif target and target.get("state") in {"FAILED", "BLOCKED"}:
        phase = "recovery"
        target_id = target.get("id")
    elif target:
        phase = "target"
        target_id = target.get("id")
    else:
        phase = "blocked-no-target"
        target_id = None

    builder = "local" if labels(issue) & PRIVATE_LABELS else "normal"
    return {
        "dispatch": "shadow",
        "candidate_count": len(candidates),
        "issue": number,
        "phase": phase,
        "builder": builder,
        "target_id": target_id,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: backlog-shadow-dispatch.py SNAPSHOT.json")
    snapshot = json.loads(Path(sys.argv[1]).read_text())
    result = plan(snapshot)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    print(
        "LIFEOS_SEMAPHORE_DISPATCH_SHADOW=PASS "
        f"dispatch={result['dispatch']} "
        f"issue={result['issue'] if result['issue'] is not None else 'none'} "
        f"phase={result['phase'] or 'none'} "
        f"builder={result['builder'] or 'none'} "
        f"target_id={result['target_id'] or 'none'} "
        f"candidate_count={result['candidate_count']} mutation=none"
    )


if __name__ == "__main__":
    main()
