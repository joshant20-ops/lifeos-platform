#!/usr/bin/env python3
"""Validated HA bridge to the local user-owned PA obligation overlay."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote_plus

import lifeos_pa_user_state
from lifeos_pa_user_state import mutate_action

STATE = Path("/config/www/lifeos_tasks.json")
ACTIONS = {"comment", "close", "reopen", "dismiss", "snooze", "severity", "due_date", "unsnooze"}
_ACTION_STAGE = "startup"
_SAFE_REASONS = {
    "task_view_unavailable_or_stale",
    "task_id_not_in_current_view",
    "user_state_directory_not_private_user_owned",
    "user_state_owner_mismatch",
    "user_state_privilege_drop_groups_failed",
    "user_state_privilege_drop_gid_failed",
    "user_state_privilege_drop_uid_failed",
}


def main():
    global _ACTION_STAGE
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--until", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--due-date", default="")
    args = parser.parse_args()
    _ACTION_STAGE = "task_view_read"
    payload = json.loads(STATE.read_text())
    _ACTION_STAGE = "task_view_validate"
    generated = int(payload.get("generated_time") or 0)
    if payload.get("schema") != "lifeos_tasks_v3" or not generated or time.time() - generated > 7 * 3600:
        raise ValueError("task_view_unavailable_or_stale")
    _ACTION_STAGE = "task_identity_validate"
    rows = (payload.get("tasks") or []) + (payload.get("resolved") or [])
    if not any(isinstance(row, dict) and row.get("id") == args.task_id for row in rows):
        raise ValueError("task_id_not_in_current_view")
    _ACTION_STAGE = "state_owner_privilege_drop"
    lifeos_pa_user_state.drop_to_state_owner()
    _ACTION_STAGE = "overlay_mutation"
    result = mutate_action(
        args.task_id,
        args.action,
        note=unquote_plus(args.note),
        until=args.until,
        severity=args.severity,
        due_date=args.due_date,
    )
    _ACTION_STAGE = "action_verify"
    if not result.get("verified"):
        raise ValueError("action_not_verified")
    print("PA_USER_ACTION=PASS")
    print("PA_USER_ACTION_KIND=" + args.action)
    print("PA_USER_STATE_REVISION=" + str(result["revision"]))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not print note text, task titles, or source evidence.
        print("PA_USER_ACTION=FAIL")
        print("PA_USER_ACTION_ERROR=" + type(exc).__name__)
        print("PA_USER_ACTION_STAGE=" + _ACTION_STAGE)
        reason = str(exc)
        if reason in _SAFE_REASONS:
            print("PA_USER_ACTION_REASON=" + reason)
        raise SystemExit(1)
