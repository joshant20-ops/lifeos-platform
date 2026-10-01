#!/usr/bin/env python3
"""User-owned LifeOS PA obligation annotations and deterministic projection.

This is a small overlay keyed by the existing obligation ID. It is not a task
store: Gmail remains source evidence and the reconciler remains the publisher.
"""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import re
import stat
import tempfile
import time
import uuid
from datetime import date, datetime

STATE_PATH = pathlib.Path(os.environ.get(
    "LIFEOS_PA_USER_STATE_PATH",
    "/opt/stacks/homeassistant/config/lifeos-pa-state/user_state.json",
))
SCHEMA = "lifeos_pa_user_state_v1"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")
SEVERITIES = {"low", "normal", "high"}
STATUSES = {"OPEN", "WAITING", "DONE", "DISMISSED"}



def drop_to_state_owner(path=None):
    """Drop a root HA action process to the private overlay directory owner."""
    target = pathlib.Path(STATE_PATH if path is None else path)
    directory = target.parent
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid == 0
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise PermissionError("user_state_directory_not_private_user_owned")
    euid = os.geteuid()
    if euid == info.st_uid:
        return
    if euid != 0:
        raise PermissionError("user_state_owner_mismatch")
    # Home Assistant invokes this bridge as root. The assistant service runs as
    # the directory owner; drop root before the atomic replacement so the 0600
    # user-state file remains readable only by that same local service account.
    for name, operation, value in (
            ("groups", os.setgroups, [info.st_gid]),
            ("gid", os.setgid, info.st_gid),
            ("uid", os.setuid, info.st_uid)):
        try:
            operation(value)
        except OSError as exc:
            raise PermissionError("user_state_privilege_drop_" + name + "_failed") from exc


def _default():
    return {"schema": SCHEMA, "revision": 0, "obligations": {}}


def read_user_state(path=None):
    path = pathlib.Path(STATE_PATH if path is None else path)
    if not path.exists():
        return _default()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("user_state_schema_invalid")
    obligations = payload.get("obligations")
    if not isinstance(obligations, dict):
        raise ValueError("user_state_obligations_invalid")
    return payload


def _write_atomic(payload, path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".user-state-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
        dirfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _valid_date(value, field):
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(field + "_invalid")
    if parsed.isoformat() != str(value):
        raise ValueError(field + "_invalid")
    return parsed.isoformat()


def mutate_action(task_id, action, *, note="", until="", severity="", due_date="", path=None, now=None):
    task_id = str(task_id or "")
    action = str(action or "")
    if not ID_RE.fullmatch(task_id):
        raise ValueError("task_id_invalid")
    if action not in {"comment", "close", "reopen", "dismiss", "snooze", "severity", "due_date", "unsnooze"}:
        raise ValueError("action_not_allowlisted")
    now = int(time.time() if now is None else now)
    path = pathlib.Path(STATE_PATH if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / ".user-state.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = read_user_state(path)
        obligations = state.setdefault("obligations", {})
        entry = dict(obligations.get(task_id) or {})
        if action == "comment":
            note = str(note or "").strip()
            if not note or len(note) > 1000:
                raise ValueError("comment_length_invalid")
            comments = list(entry.get("comments") or [])
            comments.append({
                "id": uuid.uuid4().hex,
                "created_at": now,
                "author": "user",
                "source": "user_comment",
                "text": note,
            })
            entry["comments"] = comments[-100:]
        elif action in {"close", "reopen", "dismiss"}:
            entry["status_override"] = {
                "close": "DONE",
                "reopen": "OPEN",
                "dismiss": "DISMISSED",
            }[action]
            entry["status_set_at"] = now
            entry["status_source"] = "user"
        elif action == "snooze":
            entry["snoozed_until"] = _valid_date(until, "snooze_date")
        elif action == "unsnooze":
            entry.pop("snoozed_until", None)
        elif action == "severity":
            severity = str(severity or "").lower()
            if severity not in SEVERITIES:
                raise ValueError("severity_invalid")
            entry["severity_override"] = severity
        elif action == "due_date":
            entry["due_date_override"] = _valid_date(due_date, "due_date")
        obligations[task_id] = entry
        state["revision"] = int(state.get("revision") or 0) + 1
        state["updated_at"] = now
        _write_atomic(state, path)
        verified = read_user_state(path)
        if verified.get("obligations", {}).get(task_id) != entry:
            raise ValueError("user_state_verify_failed")
        return {
            "schema": SCHEMA,
            "revision": verified["revision"],
            "task_id": task_id,
            "action": action,
            "verified": True,
        }


def apply_user_annotations(tasks, state=None):
    state = state if state is not None else read_user_state()
    obligations = state.get("obligations") or {}
    result = []
    for original in tasks or []:
        if not isinstance(original, dict):
            continue
        task = dict(original)
        task_id = str(task.get("id") or "")
        entry = obligations.get(task_id)
        if not isinstance(entry, dict):
            result.append(task)
            continue
        # Persist the machine view separately so each bounded Gmail replay starts
        # from source-derived state, not yesterday's user projection.
        machine_status = str(task.get("machine_status") or task.get("status") or "").upper()
        if machine_status in STATUSES:
            task["machine_status"] = machine_status
        override = str(entry.get("status_override") or "").upper()
        if override in STATUSES:
            task["status"] = override
            task["status_source"] = "user"
            task["status_set_at"] = int(entry.get("status_set_at") or 0)
        task["user_comments"] = [
            {
                "id": str(x.get("id") or ""),
                "created_at": int(x.get("created_at") or 0),
                "author": "user",
                "source": "user_comment",
                "text": str(x.get("text") or "")[:1000],
            }
            for x in (entry.get("comments") or [])
            if isinstance(x, dict) and x.get("source") == "user_comment"
        ][-100:]
        task["user_comment_count"] = len(task["user_comments"])
        if entry.get("snoozed_until"):
            task["snoozed_until"] = str(entry["snoozed_until"])
        else:
            task.pop("snoozed_until", None)
        if entry.get("severity_override") in SEVERITIES:
            task["severity"] = entry["severity_override"]
            task["severity_source"] = "user"
        if entry.get("due_date_override"):
            task["due_date"] = str(entry["due_date_override"])
            task["due_date_source"] = "user"
        task["user_state_revision"] = int(state.get("revision") or 0)
        result.append(task)
    return result


def _project_task(task, now_ts, today):
    status = str(task.get("status", "")).upper()
    due = task.get("due_date")
    days_until = None
    try:
        days_until = (date.fromisoformat(str(due)) - today).days if due else None
    except (TypeError, ValueError):
        due = None
    try:
        observed = int(task.get("observed_at") or 0)
    except (TypeError, ValueError):
        observed = 0
    stale_days = max(0, int((now_ts - observed) / 86400)) if observed else None
    snoozed_until = str(task.get("snoozed_until") or "")
    snoozed = False
    try:
        snoozed = status in {"OPEN", "WAITING"} and date.fromisoformat(snoozed_until) > today
    except (TypeError, ValueError):
        pass
    if days_until is not None and days_until < 0:
        urgency, due_bucket = 5, "overdue"
    elif days_until is not None and days_until <= 1:
        urgency, due_bucket = 4, "due_soon"
    elif days_until is not None and days_until <= 7:
        urgency, due_bucket = 3, "due_soon"
    elif days_until is not None and days_until <= 30:
        urgency, due_bucket = 2, "upcoming"
    else:
        urgency, due_bucket = 1, None
    severity = str(task.get("severity", "normal")).lower()
    if severity not in SEVERITIES:
        severity = "normal"
    projected = {
        "id": str(task.get("id", "")),
        "title": str(task.get("title") or "Untitled task")[:160],
        "status": status,
        "due_date": due,
        "severity": severity,
        "priority_score": {"low": 1, "normal": 2, "high": 3}[severity] * urgency,
        "due_bucket": due_bucket,
        "stale_days": stale_days,
        "source": str(task.get("source") or "gmail"),
        "source_refs": sorted(set(str(x)[:300] for x in (task.get("source_message_ids") or []) if x))[:5],
        "paperless_evidence": [
            {"document_id": x.get("document_id"), "title": str(x.get("title") or "")[:120]}
            for x in (task.get("paperless_evidence") or [])
            if isinstance(x, dict) and x.get("document_id") is not None
        ][:10],
        "observed_at": observed or None,
        "snoozed_until": snoozed_until or None,
        "snoozed": snoozed,
        "status_source": str(task.get("status_source") or "source_inference"),
        "user_comments": task.get("user_comments") or [],
        "user_comment_count": int(task.get("user_comment_count") or 0),
        "severity_source": str(task.get("severity_source") or "source_inference"),
        "due_date_source": str(task.get("due_date_source") or "source_inference"),
    }
    return projected


def derive_attention(task_rows, now_ts=None, today=None):
    now_ts = int(now_ts if now_ts is not None else time.time())
    today = today or datetime.fromtimestamp(now_ts).date()
    rows = [_project_task(task, now_ts, today) for task in task_rows if isinstance(task, dict)]
    def rank(item):
        return (-item["priority_score"], item["due_date"] or "9999-99-99", item["id"])
    outstanding = [x for x in rows if x["status"] in {"OPEN", "WAITING"}]
    active = [x for x in outstanding if not x["snoozed"]]
    needs_me = sorted([x for x in active if x["status"] == "OPEN"], key=rank)
    waiting = sorted([x for x in active if x["status"] == "WAITING"], key=rank)
    overdue = sorted([x for x in active if x["due_bucket"] == "overdue"], key=rank)
    upcoming = sorted([x for x in active if x["due_bucket"] in {"due_soon", "upcoming"}], key=rank)
    snoozed = sorted([x for x in outstanding if x["snoozed"]], key=lambda x: (x["snoozed_until"] or "9999-99-99",) + tuple(rank(x)))
    stale = [x for x in needs_me if x["stale_days"] is not None and x["stale_days"] >= 14]
    completed = sorted(
        [x for x in rows if x["status"] == "DONE" and x["observed_at"] and now_ts - x["observed_at"] <= 14 * 86400],
        key=lambda x: (-int(x["observed_at"] or 0), x["id"]),
    )
    return {
        "schema": "lifeos_attention_projection_v1",
        "generated_time": now_ts,
        "method": "deterministic_severity_times_due_urgency",
        "urgency_factors": {"overdue": 5, "due_today_or_tomorrow": 4, "due_within_7_days": 3, "due_within_30_days": 2, "no_due_date": 1},
        "counts": {
            "needs_me": len(needs_me), "waiting_on_others": len(waiting),
            "overdue": len(overdue), "upcoming": len(upcoming),
            "recently_completed": len(completed), "stale_no_progress": len(stale),
            "snoozed": len(snoozed),
        },
        "needs_me": needs_me[:20],
        "waiting_on_others": waiting[:20],
        "due_overdue": overdue[:20],
        "upcoming": upcoming[:20],
        "recently_completed": completed[:20],
        "stale_no_progress": stale[:20],
        "snoozed": snoozed[:20],
    }


def daily_briefing(attention):
    counts = attention["counts"]
    summary = (
        f"Needs you: {counts['needs_me']}; waiting on others: {counts['waiting_on_others']}; "
        f"due or overdue: {counts['overdue'] + counts['upcoming']}; "
        f"recently completed: {counts['recently_completed']}; snoozed: {counts.get('snoozed', 0)}."
    )
    picked, seen = [], set()
    for bucket in ("due_overdue", "needs_me", "waiting_on_others", "upcoming", "stale_no_progress", "recently_completed"):
        for task in attention[bucket]:
            if task["id"] and task["id"] not in seen:
                seen.add(task["id"])
                picked.append({k: task.get(k) for k in (
                    "id", "title", "status", "due_date", "severity", "source",
                    "source_refs", "paperless_evidence", "status_source",
                    "user_comments", "snoozed_until",
                )})
            if len(picked) >= 5:
                break
        if len(picked) >= 5:
            break
    return {
        "schema": "lifeos_daily_briefing_v1",
        "generated_time": attention["generated_time"],
        "source": "lifeos_tasks_v3",
        "confidence": "structured_state_only",
        "summary": summary,
        "items": picked,
    }


def apply_user_state(payload, state=None):
    if not isinstance(payload, dict) or payload.get("schema") != "lifeos_tasks_v3":
        raise ValueError("task_view_schema_invalid")
    state = state if state is not None else read_user_state()
    result = dict(payload)
    all_rows = list(payload.get("tasks") or []) + list(payload.get("resolved") or [])
    # Recover the source-derived status before applying persistent user decisions.
    machine_rows = []
    for row in all_rows:
        if not isinstance(row, dict):
            continue
        base = dict(row)
        if str(base.get("status_source") or "") == "user" and base.get("machine_status"):
            base["status"] = base["machine_status"]
        base.pop("status_source", None)
        base.pop("status_set_at", None)
        base.pop("severity_source", None)
        base.pop("due_date_source", None)
        machine_rows.append(base)
    effective = apply_user_annotations(machine_rows, state)
    result["tasks"] = [x for x in effective if str(x.get("status") or "").upper() not in {"DONE", "DISMISSED"}]
    result["resolved"] = [x for x in effective if str(x.get("status") or "").upper() in {"DONE", "DISMISSED"}]
    try:
        generated = int(result.get("generated_time") or time.time())
    except (TypeError, ValueError):
        generated = int(time.time())
    attention = derive_attention(effective, now_ts=generated)
    result["attention"] = attention
    result["briefing"] = daily_briefing(attention)
    result["user_state_revision"] = int(state.get("revision") or 0)
    return result
