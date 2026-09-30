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
    run(["systemctl", "start", "lifeos-task-reconciler.service"], timeout=1800)
    props = run(["systemctl", "show", "lifeos-task-reconciler.service", "-p", "Result", "-p", "ExecMainStatus"])
    values = dict(line.split("=", 1) for line in props.splitlines() if "=" in line)
    if values.get("Result") != "success" or values.get("ExecMainStatus") != "0":
        raise RuntimeError("reconciler_failed")
    return current_view()


def restore_state(original_bytes, original_mode, original_uid, original_gid):
    if original_bytes is None:
        try:
            USER_STATE.unlink()
        except FileNotFoundError:
            pass
    else:
        USER_STATE.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".gate-h-restore-", dir=str(USER_STATE.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(original_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(name, original_mode)
            os.chown(name, original_uid, original_gid)
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

    old = USER_STATE.stat()
    original_bytes = USER_STATE.read_bytes()
    original_mode, original_uid, original_gid = old.st_mode & 0o777, old.st_uid, old.st_gid
    before_generated = int(before.get("generated_time") or 0)
    action_changed = False
    try:
        comment_before = int(task.get("user_comment_count") or 0)
        action_changed = True
        call_ha_action("comment", task_id, note=NOTE)
        call_ha_action("snooze", task_id, until=(dt.date.today() + dt.timedelta(days=5)).isoformat())
        view = hass_projection()
        selected = next((x for x in view.get("items", []) if x.get("id") == task_id), None)
        assert selected and selected.get("user_comment_count", 0) > comment_before
        assert selected.get("user_comments", [])[-1].get("source") == "user_comment"
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

        answer = assistant_query("What needs me about " + title + "?")
        assert answer.get("provider") == "structured_local_state"
        assert answer.get("route") == "structured_pa_state"
        assert answer.get("source_schema") == "lifeos_tasks_v3"
        assert answer.get("privacy") == "local-only"
        assert task_id in answer.get("result_ids", [])
        assert target_due in answer.get("reply", "")
        assert "high" in answer.get("reply", "").lower()
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
        restore_state(original_bytes, original_mode, original_uid, original_gid)
        if action_changed:
            restored = run_reconciler()
            if read_json(PUBLISHED) != restored:
                raise RuntimeError("post_test_restore_projection_mismatch")
            print("GATE_H_TEST_STATE_CLEANUP=PASS")

    print("GATE_H_LIVE_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
