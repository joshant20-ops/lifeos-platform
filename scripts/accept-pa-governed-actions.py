#!/usr/bin/env python3
"""Live Gate H acceptance on lifeos-pi5; prints only sanitized booleans/counts."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import quote_plus

REPO = pathlib.Path("/home/joshan/lifeos-platform")
sys_path = str(REPO)
import sys
sys.path.insert(0, sys_path)
from governor import pa_user_state

TASKS = pathlib.Path("/home/joshan/automation/state/lifeos_personal_tasks.json")
PUBLISHED = pathlib.Path("/opt/stacks/homeassistant/config/www/lifeos_tasks.json")
USER_STATE = pathlib.Path("/opt/stacks/homeassistant/config/lifeos-pa-state/user_state.json")
DASHBOARD = pathlib.Path("/opt/stacks/homeassistant/config/.storage/lovelace.dashboard_lifeos")
RESOURCES = pathlib.Path("/opt/stacks/homeassistant/config/.storage/lovelace_resources")
CARD = pathlib.Path("/opt/stacks/homeassistant/config/www/lifeos-pa-task-card.js")
ASSISTANT = "http://127.0.0.1:8791"
STATE_ENV = "/config/lifeos-pa-state/user_state.json"
NOTE = "Synthetic Gate H acceptance note"


def run(argv, timeout=60, env=None):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, env=env)
    if result.returncode != 0:
        for source in (result.stdout, result.stderr):
            for line in source.splitlines():
                if line.startswith("PA_USER_ACTION_ERROR="):
                    value = line.partition("=")[2]
                    if value in {"PermissionError", "ValueError", "OSError", "RuntimeError", "FileNotFoundError"}:
                        print("GATE_H_PA_ACTION_ERROR_TYPE=" + value)
                elif line.startswith("PA_USER_ACTION_STAGE="):
                    value = line.partition("=")[2]
                    if value in {"task_view_read", "task_view_validate", "task_identity_validate", "state_owner_privilege_drop", "overlay_mutation", "action_verify"}:
                        print("GATE_H_PA_ACTION_STAGE=" + value)
                elif line.startswith("PA_USER_ACTION_REASON="):
                    value = line.partition("=")[2]
                    if value in {
                        "task_view_unavailable_or_stale", "task_id_not_in_current_view",
                        "user_state_directory_not_private_user_owned", "user_state_owner_mismatch",
                        "user_state_privilege_drop_groups_failed", "user_state_privilege_drop_gid_failed",
                        "user_state_privilege_drop_uid_failed",
                    }:
                        print("GATE_H_PA_ACTION_REASON=" + value)
        raise RuntimeError("bounded_runtime_command_failed")
    return result.stdout


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def current_view():
    payload = read_json(TASKS)
    if payload.get("schema") != "lifeos_tasks_v3":
        raise RuntimeError("task_schema_invalid")
    return payload


def call_ha_action(action, task_id, *, note="", until="", severity="", due_date=""):
    encoded_note = quote_plus(note)
    result = run([
        "docker", "exec",
        "-e", "LIFEOS_PA_USER_STATE_PATH=" + STATE_ENV,
        "homeassistant", "python3", "/config/scripts/lifeos_pa_user_action.py",
        "--action", action, "--task-id", task_id, "--note", encoded_note,
        "--until", until, "--severity", severity, "--due-date", due_date,
    ], timeout=30)
    if "PA_USER_ACTION=PASS" not in result:
        raise RuntimeError("ha_action_not_verified")


def hass_projection():
    result = run([
        "docker", "exec", "-e", "LIFEOS_PA_USER_STATE_PATH=" + STATE_ENV,
        "homeassistant", "python3", "/config/scripts/lifeos_pa_task_attention_sensor.py",
    ], timeout=30)
    return json.loads(result)


def assistant_query(question):
    body = json.dumps({
        "messages": [{"role": "user", "content": question}],
        "privacy_domain": "personal-administration",
    }).encode()
    request = urllib.request.Request(
        ASSISTANT + "/assist",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError("assistant_http_failed")
        return json.loads(response.read().decode())


def run_reconciler():
    started = dt.datetime.now(dt.timezone.utc)
    run(["systemctl", "start", "lifeos-task-reconciler.service"], timeout=1800)
    props = run(["systemctl", "show", "lifeos-task-reconciler.service", "-p", "Result", "-p", "ExecMainStatus"])
    values = dict(line.split("=", 1) for line in props.splitlines() if "=" in line)
    if values.get("Result") != "success" or values.get("ExecMainStatus") != "0":
        raise RuntimeError("reconciler_failed")
    since = started.strftime("%Y-%m-%d %H:%M:%S UTC")
    journal = run(["journalctl", "-u", "lifeos-task-reconciler.service", "--since", since, "--no-pager", "-o", "cat"])
    safe_fields = {
        "TASK_FETCH_ERRORS": "FETCH_ERRORS",
        "TASK_FETCH_ERROR_TYPES": "FETCH_ERROR_TYPES",
        "TASK_CLASSIFICATION_ERRORS": "CLASSIFICATION_ERRORS",
        "TASK_CLASSIFICATION_ERROR_TYPES": "CLASSIFICATION_ERROR_TYPES",
    }
    for line in journal.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in safe_fields:
            continue
        safe_value = "".join(ch for ch in value if ch.isalnum() or ch in "_,")
        print("GATE_H_RECONCILER_" + safe_fields[key] + "=" + (safe_value or "UNAVAILABLE"))
    payload = current_view()
    print("GATE_H_FRESH_RECONCILIATION_ERRORS=" + str(int(payload.get("errors") or 0)))
    return payload


def restore_state(original_bytes):
    if original_bytes is None:
        try:
            USER_STATE.unlink()
        except FileNotFoundError:
            pass
    else:
        directory = USER_STATE.parent
        directory_info = directory.lstat()
        if not directory.is_dir() or directory_info.st_uid == 0 or directory_info.st_mode & 0o777 != 0o700:
            raise RuntimeError("user_state_directory_not_private_user_owned")
        fd, name = tempfile.mkstemp(prefix=".gate-h-restore-", dir=str(directory))
        try:
            os.fchown(fd, directory_info.st_uid, directory_info.st_gid)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(original_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, USER_STATE)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass


def main():
    if subprocess.check_output(["hostname"], text=True).strip() != "Docker":
        raise RuntimeError("wrong_runtime_host")
    before = current_view()
    rows = list(before.get("tasks") or []) + list(before.get("resolved") or [])
    candidates = [x for x in rows if isinstance(x, dict) and x.get("id") and x.get("status") in {"OPEN", "WAITING"}]
    if not candidates:
        candidates = [x for x in rows if isinstance(x, dict) and x.get("id")]
    if not candidates:
        print("GATE_H_RUNTIME_TASK=FAIL")
        raise RuntimeError("no_existing_obligation")
    task = candidates[0]
    task_id = str(task["id"])
    title = str(task.get("title") or "Untitled obligation")
    if not pa_user_state.ID_RE.fullmatch(task_id):
        raise RuntimeError("runtime_task_id_invalid")

    original_bytes = USER_STATE.read_bytes()
    prior_user_state = pa_user_state.read_user_state()
    prior_entry = (prior_user_state.get("obligations") or {}).get(task_id) or {}
    comment_ids_before = {
        str(item.get("id")) for item in (prior_entry.get("comments") or [])
        if isinstance(item, dict) and item.get("id")
    }
    before_generated = int(before.get("generated_time") or 0)
    action_changed = False
    try:
        action_changed = True
        call_ha_action("comment", task_id, note=NOTE)
        call_ha_action("snooze", task_id, until=(dt.date.today() + dt.timedelta(days=5)).isoformat())
        view = hass_projection()
        selected = next((x for x in view.get("items", []) if x.get("id") == task_id), None)
        overlay_entry = (pa_user_state.read_user_state().get("obligations") or {}).get(task_id) or {}
        overlay_comments = overlay_entry.get("comments") or []
        projected_comments = selected.get("user_comments") or [] if selected else []
        print("GATE_H_COMMENT_PROJECTION_ITEM_PRESENT=" + ("PASS" if selected else "FAIL"))
        print("GATE_H_COMMENT_OVERLAY_PRESENT=" + ("PASS" if any(isinstance(x, dict) and x.get("source") == "user_comment" and x.get("text") == NOTE for x in overlay_comments) else "FAIL"))
        latest_comment = projected_comments[-1] if projected_comments else {}
        print("GATE_H_COMMENT_PROJECTION_COUNT_PARITY=" + ("PASS" if selected and int(selected.get("user_comment_count") or 0) == len(projected_comments) else "FAIL"))
        print("GATE_H_COMMENT_PROJECTION_NEW_ID=" + ("PASS" if latest_comment.get("id") and str(latest_comment.get("id")) not in comment_ids_before else "FAIL"))
        print("GATE_H_COMMENT_PROJECTION_NOTE_MATCH=" + ("PASS" if latest_comment.get("text") == NOTE and latest_comment.get("source") == "user_comment" else "FAIL"))
        print("GATE_H_SNOOZE_PROJECTION=" + ("PASS" if selected and selected.get("snoozed") is True else "FAIL"))
        assert selected and projected_comments
        assert int(selected.get("user_comment_count") or 0) == len(projected_comments)
        assert str(latest_comment.get("id") or "") not in comment_ids_before
        assert latest_comment.get("source") == "user_comment"
        assert selected.get("user_comments", [])[-1].get("text") == NOTE
        assert selected.get("snoozed") is True
        assert task_id not in {x.get("id") for x in (view.get("items") or []) if not x.get("snoozed")}
        print("GATE_H_COMMENT_AND_SNOOZE=PASS")

        call_ha_action("close", task_id)
        closed = run_reconciler()
        closed_rows = list(closed.get("tasks") or []) + list(closed.get("resolved") or [])
        closed_task = next(x for x in closed_rows if x.get("id") == task_id)
        assert int(closed.get("generated_time") or 0) > before_generated
        assert closed_task.get("status") == "DONE"
        assert closed_task.get("status_source") == "user"
        assert int(closed.get("errors") or 0) == 0
        assert read_json(PUBLISHED) == closed
        replay_fixture = {
            "schema": "lifeos_tasks_v3",
            "generated_time": int(time.time()),
            "tasks": [{**task, "status": "OPEN"}],
            "resolved": [],
        }
        replayed = pa_user_state.apply_user_state(replay_fixture, pa_user_state.read_user_state())
        replay_row = next(x for x in list(replayed["tasks"]) + list(replayed["resolved"]) if x.get("id") == task_id)
        assert replay_row.get("status") == "DONE" and replay_row.get("machine_status") == "OPEN"
        print("GATE_H_CLOSE_SURVIVES_FRESH_RECONCILIATION_AND_SOURCE_REPLAY=PASS")

        call_ha_action("reopen", task_id)
        call_ha_action("unsnooze", task_id)
        target_due = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        call_ha_action("severity", task_id, severity="high")
        call_ha_action("due_date", task_id, due_date=target_due)
        view = hass_projection()
        selected = next((x for x in view.get("items", []) if x.get("id") == task_id), None)
        assert selected and selected.get("status") == "OPEN"
        assert selected.get("severity") == "high" and selected.get("severity_source") == "user"
        assert selected.get("due_date") == target_due and selected.get("due_date_source") == "user"
        assert selected.get("snoozed") is False
        assert view.get("source") == "lifeos_tasks_v3"

        answer = assistant_query("What needs me about " + task_id + "?")
        assert answer.get("provider") == "structured_local_state"
        assert answer.get("route") == "structured_pa_state"
        assert answer.get("source_schema") == "lifeos_tasks_v3"
        assert answer.get("privacy") == "local-only"
        result_ids = answer.get("result_ids", [])
        reply = str(answer.get("reply", ""))
        if not isinstance(result_ids, list):
            result_ids = []
        # Content-safe diagnostics: never print task IDs, titles, comments, or replies.
        confidence = answer.get("confidence")
        print("GATE_H_ASSIST_CONFIDENCE=" + ("structured_state_only" if confidence == "structured_state_only" else "unavailable" if confidence == "unavailable" else "other"))
        print("GATE_H_ASSIST_RESULT_COUNT=" + str(len(result_ids)))
        print("GATE_H_ASSIST_TARGET_ID_MATCH=" + ("PASS" if task_id in result_ids else "FAIL"))
        print("GATE_H_ASSIST_DUE_OVERRIDE_VISIBLE=" + ("PASS" if target_due in reply else "FAIL"))
        print("GATE_H_ASSIST_SEVERITY_OVERRIDE_VISIBLE=" + ("PASS" if "high" in reply.lower() else "FAIL"))
        assert task_id in result_ids
        assert target_due in reply
        assert "high" in reply.lower()
        print("GATE_H_REOPEN_OVERRIDES_HA_AND_CONVERSATIONAL_RETRIEVAL=PASS")

        dashboard = read_json(DASHBOARD)
        overview = next(v for v in dashboard["data"]["config"]["views"] if v.get("path") == "overview")
        card = next(c for c in overview.get("cards", []) if c.get("type") == "custom:lifeos-pa-task-card")
        assert card.get("entity") == "sensor.lifeos_pa_task_attention"
        resource_items = read_json(RESOURCES).get("data", {}).get("items", [])
        assert any(x.get("id") == "lifeos-pa-task-card" and x.get("type") == "module" for x in resource_items)
        assert CARD.is_file() and CARD.stat().st_size > 100
        print("GATE_H_EXISTING_OVERVIEW_CONTROLS=PASS")

        units = run(["systemctl", "list-unit-files", "--no-legend", "--no-pager"])
        services = [x.split()[0] for x in units.splitlines() if x.split() and "task-reconciler" in x and x.split()[0].endswith(".service")]
        timers = [x.split()[0] for x in units.splitlines() if x.split() and "task-reconciler" in x and x.split()[0].endswith(".timer")]
        assert services == ["lifeos-task-reconciler.service"]
        assert timers == ["lifeos-task-reconciler.timer"]
        print("GATE_H_SINGLE_PUBLISHER_SERVICE_TIMER=PASS")
    finally:
        restore_state(original_bytes)
        restored_dir = USER_STATE.parent.stat()
        if USER_STATE.exists():
            restored_file = USER_STATE.stat()
            assert restored_file.st_uid == restored_dir.st_uid and restored_file.st_gid == restored_dir.st_gid
            assert restored_file.st_mode & 0o777 == 0o600
        lock_file = USER_STATE.parent / ".user-state.lock"
        if lock_file.exists():
            restored_lock = lock_file.stat()
            assert restored_lock.st_uid == restored_dir.st_uid and restored_lock.st_gid == restored_dir.st_gid
            assert restored_lock.st_mode & 0o777 == 0o600
        print("GATE_H_USER_STATE_CLEANUP_PRIVATE=PASS")
        if action_changed:
            restored = run_reconciler()
            if read_json(PUBLISHED) != restored:
                raise RuntimeError("post_test_restore_projection_mismatch")
            print("GATE_H_TEST_STATE_CLEANUP=PASS")

    print("GATE_H_LIVE_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
