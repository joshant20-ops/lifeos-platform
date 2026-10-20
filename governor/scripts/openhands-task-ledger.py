#!/usr/bin/env python3
"""Solution-neutral engineering milestone ledger and deterministic recovery cue."""

from __future__ import annotations

import json
import sys

OBJECTIVES = (
    ("task_understood", "understand the issue and acceptance criteria"),
    ("implementation_inspected", "inspect the relevant implementation"),
    ("defect_established", "establish the defect with deterministic evidence"),
    ("implementation_changed", "make an implementation change"),
    ("tests_executed", "execute relevant tests"),
    ("diff_reviewed", "review the resulting diff"),
    ("committed", "commit the completed change on a task branch"),
    ("pushed", "push the task branch"),
    ("pr_created", "create a pull request"),
    ("ci_checked", "check CI and respond to failures"),
)


def assess(snapshot: dict) -> dict:
    completed = {name: bool(snapshot.get(name)) for name, _ in OBJECTIVES}
    earliest = next(
        ({"name": name, "objective": objective} for name, objective in OBJECTIVES if not completed[name]),
        None,
    )
    repeated = int(snapshot.get("repeated_action_count") or 0)
    result = {
        "completed": completed,
        "earliest_unmet": earliest,
        "complete": earliest is None,
        "stalled": repeated >= 3,
    }
    return result


def recovery_message(result: dict, task_context: str = "") -> str:
    unmet = result.get("earliest_unmet")
    if not unmet:
        return "All engineering objectives are complete. Perform a concise final completeness check."
    prefix = (
        "Deterministic progress check: no objective advanced during repeated actions. "
        if result.get("stalled")
        else "Deterministic progress check: the task is incomplete. "
    )
    context = (
        "Authoritative task context repeated from the original request (retain its objective and constraints):\n"
        + task_context.strip()
        + "\n\n"
        if task_context.strip()
        else ""
    )
    return context + (
        prefix
        + f"Earliest unmet objective: {unmet['objective']}. "
        + "Use the repeated authoritative task context above as the source of truth. "
        + "Do not switch to repository-wide backlog items, list the whole repository, "
        + "or reread task trackers unless the task requires it. "
        + "Take one focused tool action that directly advances this objective. "
        + "Use only tools exposed in this session and their declared argument schemas. "
        + "For shell work, use the supplied terminal tool with its declared command argument. "
        + "After a tool error, follow the reported available tools and schema; do not retry unsupported aliases. "
        + "Do not repeat a prior action unless it produces new evidence, and do not stop before the branch, PR, and CI cycle is complete."
    )


def main() -> int:
    snapshot = json.load(sys.stdin)
    result = assess(snapshot)
    result["recovery_message"] = recovery_message(result, str(snapshot.get("task_context") or ""))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
