#!/usr/bin/env python3
"""Validated HA bridge to the local user-owned PA obligation overlay."""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import unquote_plus

import lifeos_pa_user_state
from lifeos_pa_user_state import mutate_action

STATE = Path("/config/www/lifeos_tasks.json")
ACTIONS = {"comment", "close", "reopen", "dismiss", "snooze", "severity", "due_date", "unsnooze", "junk", "review", "signin_yes", "signin_no", "signin_unsure"}
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


def _enqueue_request_atomically(path, request):
    """Publish a complete JSON request before the watched *.json path appears."""
    temp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(request, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            return False
        return True
    finally:
        temp.unlink(missing_ok=True)



def main():
    global _ACTION_STAGE
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS))
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--until", default="")
    parser.add_argument("--severity", default="")
    parser.add_argument("--due-date", default="")
    parser.add_argument("--paperless-ids", default="")
    args = parser.parse_args()
    _ACTION_STAGE = "task_view_read"
    payload = json.loads(STATE.read_text())
    _ACTION_STAGE = "task_view_validate"
    generated = int(payload.get("generated_time") or 0)
    if payload.get("schema") != "lifeos_tasks_v3" or not generated or time.time() - generated > 7 * 3600:
        raise ValueError("task_view_unavailable_or_stale")
    _ACTION_STAGE = "task_identity_validate"
    rows = (payload.get("tasks") or []) + (payload.get("resolved") or []) + (payload.get("informational") or [])
    task = next((row for row in rows if isinstance(row, dict) and row.get("id") == args.task_id), None)
    if task is None:
        raise ValueError("task_id_not_in_current_view")
    if args.action.startswith("signin_"):
        if not any(event.get("id")==unquote_plus(args.note) for event in task.get("sign_in_events") or [] if isinstance(event,dict)):
            raise ValueError("signin_event_not_in_current_view")
    if task.get("obligation_suppressed") and args.action not in {"review","comment","reopen"}:
        raise ValueError("informational_action_not_allowed")
    if args.action == "review":
        _ACTION_STAGE = "review_request_validate"
        if str(task.get("status") or "").upper() not in {"OPEN", "WAITING", "DONE", "DISMISSED"}:
            raise ValueError("task_status_invalid")
        _ACTION_STAGE = "state_owner_privilege_drop"
        lifeos_pa_user_state.drop_to_state_owner()
        _ACTION_STAGE = "review_request_enqueue"
        queue_dir = lifeos_pa_user_state.STATE_PATH.parent / "review-requests"
        if not queue_dir.is_dir():
            raise ValueError("review_queue_unavailable")
        request = {
            "schema": "lifeos_pa_review_request_v1",
            "request_id": uuid.uuid4().hex,
            "task_id": args.task_id,
            "requested_at": int(time.time()),
        }
        request_path = queue_dir / (args.task_id + ".json")
        stale_failure = queue_dir / "failed" / request_path.name
        try:
            stale_failure.unlink()
        except FileNotFoundError:
            pass
        if not _enqueue_request_atomically(request_path, request):
            print("PA_USER_ACTION=QUEUED")
            print("PA_USER_ACTION_KIND=review")
            return
        print("PA_USER_ACTION=QUEUED")
        print("PA_USER_ACTION_KIND=review")
        return
    if args.action == "junk":
        ids = sorted(set(x for x in args.paperless_ids.split(",") if x))
        if len(ids) > 10 or any(not x.isdigit() or int(x) <= 0 for x in ids):
            raise ValueError("paperless_selection_invalid")
        linked = {
            str(doc.get("document_id"))
            for doc in (task.get("paperless_evidence") or [])
            if isinstance(doc, dict) and doc.get("document_id") is not None
        }
        if not set(ids).issubset(linked):
            raise ValueError("paperless_selection_not_linked")
        refs = task.get("source_message_ids") or []
        if not refs:
            raise ValueError("source_email_unavailable")
        if str(task.get("status") or "").upper() not in {"OPEN", "WAITING"}:
            raise ValueError("task_not_open")
        _ACTION_STAGE = "state_owner_privilege_drop"
        lifeos_pa_user_state.drop_to_state_owner()
        _ACTION_STAGE = "junk_request_enqueue"
        queue_dir = lifeos_pa_user_state.STATE_PATH.parent / "junk-requests"
        if not queue_dir.is_dir():
            raise ValueError("junk_queue_unavailable")
        request = {
            "schema": "lifeos_pa_junk_request_v1",
            "request_id": uuid.uuid4().hex,
            "task_id": args.task_id,
            "paperless_document_ids": [int(x) for x in ids],
            "requested_at": int(time.time()),
        }
        request_path = queue_dir / (args.task_id + ".json")
        if not _enqueue_request_atomically(request_path, request):
            print("PA_USER_ACTION=QUEUED")
            print("PA_USER_ACTION_KIND=junk")
            return
        print("PA_USER_ACTION=QUEUED")
        print("PA_USER_ACTION_KIND=junk")
        return
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
