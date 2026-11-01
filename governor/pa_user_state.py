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
    if euid != 0 and euid != info.st_uid:
        raise PermissionError("user_state_owner_mismatch")

    # A previous root-run action could leave either file root-owned. Repair
    # metadata only inside the validated 0700 directory before dropping root.
    # The content remains local and the files stay owner-only.
    for candidate in (target, directory / ".user-state.lock"):
        try:
            file_info = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(file_info.st_mode):
            raise PermissionError("user_state_file_not_regular")
        if file_info.st_uid != info.st_uid or file_info.st_gid != info.st_gid:
            if euid != 0:
                raise PermissionError("user_state_file_owner_mismatch")
            os.chown(candidate, info.st_uid, info.st_gid, follow_symlinks=False)
        if stat.S_IMODE(file_info.st_mode) != 0o600:
            os.chmod(candidate, 0o600, follow_symlinks=False)

    if euid == info.st_uid:
        return
    # Home Assistant invokes this bridge as root. The assistant service runs as
    # the directory owner; drop root before the atomic replacement so both the
    # user-state file and its persistent lock remain private to that account.
    for name, operation, value in (
            ("groups", os.setgroups, [info.st_gid]),
            ("gid", os.setgid, info.st_gid),
            ("uid", os.setuid, info.st_uid)):
        try:
            operation(value)
        except OSError as exc:
            raise PermissionError("user_state_privilege_drop_" + name + "_failed") from exc


def explicit_tracking(entry):
    """A user's active status/date/priority decision outranks automatic holding."""
    if not isinstance(entry, dict) or entry.get("status_override") in {"DONE", "DISMISSED"}:
        return False
    return entry.get("status_override") in {"OPEN", "WAITING"} or bool(entry.get("due_date_override") or entry.get("severity_override"))


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


def waiting_confirmation_applies(task, decision, entry):
    """Owner waiting applies to reviewed evidence, never unseen requests."""
    if not isinstance(decision, dict) or not decision.get("source_ids"):
        return False
    if (int(entry.get("status_set_at") or 0) > int(decision.get("confirmed_at") or 0)
            or int(entry.get("status_revision") or 0) > int(decision.get("confirmed_revision") or 0)
            or task.get("sign_in_events")):
        return False
    reviewed = set(decision["source_ids"])
    ids = set(task.get("source_message_ids") or [])
    if task.get("email_message_id"):
        ids.add(task["email_message_id"])
    if not reviewed.issubset(ids):
        return False
    for source_id in ids - reviewed:
        events = [event for event in task.get("timeline_events") or []
                  if isinstance(event, dict) and event.get("message_id") == source_id]
        if not events or any(event.get("event_kind") != "information" or event.get("evidence_only")
                             or event.get("status") not in {"NONE", None} for event in events):
            return False
    return True


def confirm_reviewed_project(payload, *, provider, expected_count, expected_active,
                             reviewed_before, confirmation_ref, path=None, now=None):
    """One atomic owner annotation on exact local records, not a source classifier.

    Called by the governed deployment only after a specific owner confirmation.
    Source identifiers and the original-state backup never leave the local host.
    """
    from email.utils import parseaddr
    now = int(time.time() if now is None else now)
    path = pathlib.Path(STATE_PATH if path is None else path)
    if not re.fullmatch(r"[a-z0-9-]{12,100}", confirmation_ref):
        raise ValueError("owner_confirmation_ref_invalid")
    with (path.parent / ".user-state.lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = read_user_state(path)
        if confirmation_ref in (state.get("confirmations") or {}):
            return {"result": "ALREADY_APPLIED", "members": len(state["confirmations"][confirmation_ref]["member_ids"])}
        generated = int(payload.get("generated_time") or 0)
        if payload.get("schema") != "lifeos_tasks_v3" or not (reviewed_before - 7*3600 <= generated <= reviewed_before):
            raise ValueError("owner_review_snapshot_changed")
        rows = [row for key in ("tasks", "resolved", "informational") for row in payload.get(key) or []]
        selected = []
        for row in rows:
            context = row.get("source_context") or {}
            ids = set(row.get("source_message_ids") or [])
            if row.get("email_message_id"): ids.add(row["email_message_id"])
            if context.get("message_id") not in ids:
                continue
            if parseaddr(context.get("sender") or "")[1].lower().rpartition("@")[2] == provider:
                selected.append(row)
        ids = sorted(row["id"] for row in selected)
        active = [row for row in selected if not row.get("obligation_suppressed")]
        if (len(ids) != expected_count or len(set(ids)) != len(ids) or len(active) != expected_active
                or any(not ID_RE.fullmatch(value) for value in ids)
                or any(row.get("status") not in {"OPEN", "WAITING"} for row in active)
                or any((row.get("source_disposition_checks") or {}).get("missing", 0) for row in selected)):
            raise ValueError("owner_review_membership_changed")
        if any(max(int((state["obligations"].get(value) or {}).get("status_set_at") or 0),
                       int(((state["obligations"].get(value) or {}).get("project") or {}).get("set_at") or 0)) > reviewed_before for value in ids):
            raise ValueError("owner_decision_changed_after_review")
        anchor = ids[0]
        for row in selected:
            source_ids = sorted(set(row.get("source_message_ids") or []) | ({row["email_message_id"]} if row.get("email_message_id") else set()))
            if not source_ids:
                raise ValueError("owner_review_source_missing")
        backup = path.with_name("user-state-before-" + confirmation_ref + ".json")
        if backup.exists():
            if backup.is_symlink() or json.loads(backup.read_text()) != state:
                raise ValueError("owner_confirmation_backup_conflict")
        else:
            _write_atomic(state, backup)
        supplier = str(selected[0].get("counterparty") or "").strip()
        outcome = "Buy and collect " + ((supplier + " vehicle") if supplier else "vehicle")
        for row in selected:
            entry = dict(state["obligations"].get(row["id"]) or {})
            entry["project"] = {"anchor_id": anchor, "set_at": now, "confirmation_ref": confirmation_ref}
            if row["id"] == anchor:
                entry["project"].update(outcome=outcome, state="active")
            if row in active:
                entry["waiting_confirmation"] = {
                    "source_ids": sorted(set(row.get("source_message_ids") or []) | ({row["email_message_id"]} if row.get("email_message_id") else set())),
                    "confirmed_at": now, "confirmed_revision": int(state.get("revision") or 0) + 1, "confirmation_ref": confirmation_ref,
                    "waiting_for": "Vehicle and collection assignment",
                }
            state["obligations"][row["id"]] = entry
        state.setdefault("confirmations", {})[confirmation_ref] = {
            "source": "owner_confirmation", "confirmed_at": now, "reviewed_before": reviewed_before,
            "anchor_id": anchor, "member_ids": ids, "revision": int(state.get("revision") or 0) + 1,
            "source_ids_by_matter": {row["id"]: sorted(set(row.get("source_message_ids") or []) | ({row["email_message_id"]} if row.get("email_message_id") else set())) for row in selected},
        }
        state["revision"] = int(state.get("revision") or 0) + 1
        state["updated_at"] = now
        _write_atomic(state, path)
        if read_user_state(path) != state:
            raise ValueError("owner_confirmation_verify_failed")
        return {"result": "APPLIED", "members": len(ids)}


def mutate_action(task_id, action, *, note="", until="", severity="", due_date="", path=None, now=None):
    task_id = str(task_id or "")
    action = str(action or "")
    if not ID_RE.fullmatch(task_id):
        raise ValueError("task_id_invalid")
    if action not in {"comment", "close", "reopen", "dismiss", "snooze", "severity", "due_date", "unsnooze", "signin_yes", "signin_no", "signin_unsure", "project_outcome", "project_complete", "project_reopen"}:
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
        if action.startswith("signin_"):
            event_id=str(note or "")
            if not re.fullmatch(r"[a-f0-9]{64}",event_id):
                raise ValueError("signin_event_id_invalid")
            # This explicit answer supersedes an earlier whole-matter close.
            # A subsequent explicit close/reopen still wins until answered again.
            for field in ("status_override","status_set_at","status_source","status_revision"):
                entry.pop(field,None)
            decisions=dict(entry.get("signin_decisions") or {})
            decisions[event_id]={"answer":action.removeprefix("signin_"),"answered_at":now}
            entry["signin_decisions"]=decisions
        elif action == "project_outcome":
            outcome = str(note or "").strip()
            if not outcome or len(outcome) > 240:
                raise ValueError("project_outcome_length_invalid")
            entry["project"] = {**(entry.get("project") or {}), "outcome": outcome, "state": "active", "set_at": now}
        elif action in {"project_complete", "project_reopen"}:
            project = dict(entry.get("project") or {})
            if not project.get("outcome"):
                raise ValueError("project_outcome_required")
            project.update(state="complete" if action == "project_complete" else "active", set_at=now)
            entry["project"] = project
        elif action == "comment":
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
            entry["status_revision"] = int(state.get("revision") or 0) + 1
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


def apply_user_annotations(tasks, state=None, *, now_ts=None):
    state = state if state is not None else read_user_state()
    try:
        projection_today = datetime.fromtimestamp(int(now_ts if now_ts is not None else time.time())).date()
    except (TypeError, ValueError, OverflowError, OSError):
        projection_today = datetime.now().date()
    obligations = state.get("obligations") or {}
    result = []
    for original in tasks or []:
        if not isinstance(original, dict):
            continue
        task = dict(original)
        task_id = str(task.get("id") or "")
        if task.get("due_date_source")=="paperless_policy":
            task.pop("date_confirmation_required",None)
        task.pop("user_project", None)
        task.pop("user_waiting_for", None)
        task.pop("waiting_confirmation_ref", None)
        entry = obligations.get(task_id)
        if explicit_tracking(entry):
            task.pop("confirmation_required",None)
        events=[dict(event) for event in task.get("sign_in_events") or [] if isinstance(event,dict)]
        decisions=(entry or {}).get("signin_decisions") or {}
        for event in events:
            decision=decisions.get(event.get("id")) or {}
            event["answer"]=decision.get("answer") if decision.get("answer") in {"yes","no","unsure"} else None
            event["answered_at"]=decision.get("answered_at")
        task["sign_in_events"]=events
        if events and all(event.get("answer")=="yes" for event in events) and set(task.get("source_message_ids") or []) == {event.get("source_message_id") for event in events}:
            task["machine_status"]=task.get("machine_status") or task.get("status")
            task["status"]="DONE"
            task["status_source"]="user_confirmation"
        elif events and any(event.get("answer") in {"no","unsure"} for event in events):
            task["machine_status"]=task.get("machine_status") or task.get("status")
            task["status"]="OPEN"
            task["status_source"]="user_confirmation"
        if not isinstance(entry, dict):
            until = str(task.get("snoozed_until") or "")
            try:
                snooze_is_active = (
                    task.get("status") in {"OPEN", "WAITING"}
                    and date.fromisoformat(until) > projection_today
                )
            except (TypeError, ValueError):
                snooze_is_active = False
            if not snooze_is_active:
                task.pop("snoozed_until", None)
            result.append(task)
            continue
        project = entry.get("project")
        if isinstance(project, dict) and (project.get("outcome") or project.get("anchor_id")) and project.get("state", "active") in {"active", "complete"}:
            task["user_project"] = {"outcome": str(project.get("outcome") or "")[:240], "state": project.get("state", "active"),
                                    "anchor_id": project.get("anchor_id"), "confirmation_ref": project.get("confirmation_ref"),
                                    "set_at": int(project.get("set_at") or 0), "source": "user"}
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
        waiting = entry.get("waiting_confirmation")
        if (not task.get("obligation_suppressed") and task.get("status") in {"OPEN", "WAITING"}
                and waiting_confirmation_applies(task, waiting, entry)):
            task["status"] = "WAITING"
            task["status_source"] = "user_waiting_confirmation"
            task["status_set_at"] = int(waiting["confirmed_at"])
            task["user_waiting_for"] = str(waiting.get("waiting_for") or "")[:240]
            task["waiting_confirmation_ref"] = waiting.get("confirmation_ref")
            task.pop("confirmation_required", None)
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
        until = str(entry.get("snoozed_until") or "")
        try:
            snooze_is_active = (
                task.get("status") in {"OPEN", "WAITING"}
                and date.fromisoformat(until) > projection_today
            )
        except (TypeError, ValueError):
            snooze_is_active = False
        if snooze_is_active:
            task["snoozed_until"] = until
        else:
            task.pop("snoozed_until", None)
        if entry.get("severity_override") in SEVERITIES:
            if "machine_severity" not in task:
                task["machine_severity"]=task.get("severity")
                task["machine_severity_source"]=task.get("severity_source")
            task["severity"] = entry["severity_override"]
            task["severity_source"] = "user"
        if entry.get("due_date_override"):
            if "machine_due_date" not in task:
                task["machine_due_date"]=task.get("due_date")
                task["machine_due_date_source"]=task.get("due_date_source")
                task["machine_date_confirmation_required"]=bool(task.get("date_confirmation_required"))
            task["due_date"] = str(entry["due_date_override"])
            task["due_date_source"] = "user"
            task.pop("date_confirmation_required",None)
        task["user_state_revision"] = int(state.get("revision") or 0)
        result.append(task)
    return result


def _project_task(task, now_ts, today):
    status = str(task.get("status", "")).upper()
    due = task.get("due_date")
    confirmation=task.get("confirmation_required") if status in {"OPEN","WAITING"} else None
    extracted_date=due
    date_verified=task.get("due_date_source") in {"user","paperless_policy"}
    if (confirmation in {"optional_commitment","past_event_status"} or task.get("date_confirmation_required")) and not date_verified:
        due=None
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
        "title": (("Confirm whether to track: " if confirmation=="optional_commitment" else "Review source for: " if confirmation=="source_unavailable" else "Review past event: " if confirmation=="past_event_status" else "") + str(task.get("title") or "Untitled task"))[:200],
        "confirmation_required": confirmation,
        "extracted_date": extracted_date,
        "status": "OPEN" if confirmation else status,
        "source_status": status,
        "due_date": due,
        "severity": severity,
        "priority_score": {"low": 1, "normal": 2, "high": 3}[severity] * urgency,
        "due_bucket": due_bucket,
        "stale_days": stale_days,
        "source": str(task.get("source") or "gmail"),
        "waiting_context": ({
            "counterparty": " ".join(str(task.get("counterparty") or "").split())[:100],
            "topic": " ".join(str(task.get("topic") or "").split())[:120],
            "reason": " ".join(str(task.get("user_waiting_for") or task.get("reason") or "").split())[:240],
        } if status == "WAITING" else None),
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



def project_task_for_attention(task, now_ts=None):
    """Render source rows with the same commitment/date semantics as attention."""
    now_ts=int(now_ts if now_ts is not None else time.time())
    return _project_task(task,now_ts,datetime.fromtimestamp(now_ts).date())


def order_tasks_for_attention(task_rows, now_ts=None):
    """Return every current task in the same priority order used by PA attention."""
    now_ts = int(now_ts if now_ts is not None else time.time())
    today = datetime.fromtimestamp(now_ts).date()

    def rank(task):
        projected = _project_task(task, now_ts, today)
        status = projected["status"]
        if status == "OPEN" and not projected["snoozed"]:
            bucket = 0
        elif status == "WAITING" and not projected["snoozed"]:
            bucket = 1
        elif status in {"OPEN", "WAITING"}:
            bucket = 2
        elif status == "DONE":
            bucket = 3
        elif status == "DISMISSED":
            bucket = 4
        else:
            bucket = 5
        within_bucket = (
            -int(projected["observed_at"] or 0)
            if bucket == 3
            else -int(projected["priority_score"])
        )
        return (
            bucket,
            within_bucket,
            projected["due_date"] or "9999-99-99",
            projected["title"].casefold(),
            projected["id"],
        )

    return sorted(
        (task for task in task_rows or [] if isinstance(task, dict)),
        key=rank,
    )

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
                    "user_comments", "snoozed_until", "confirmation_required", "extracted_date",
                    "waiting_context",
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
    try:
        generated = int(result.get("generated_time") or time.time())
    except (TypeError, ValueError):
        generated = int(time.time())
    information_ids={row.get("id") for row in payload.get("informational") or [] if isinstance(row,dict)}
    all_rows = [row for row in list(payload.get("tasks") or []) + list(payload.get("resolved") or []) if isinstance(row,dict) and row.get("id") not in information_ids]
    # Recover the source-derived status before applying persistent user decisions.
    machine_rows = []
    for row in all_rows:
        if not isinstance(row, dict):
            continue
        base = dict(row)
        if str(base.get("status_source") or "") in {"user", "user_confirmation", "user_waiting_confirmation"} and base.get("machine_status"):
            base["status"] = base["machine_status"]
        # A projected owner decision is not the underlying source value.
        if "machine_due_date" in base:
            base["due_date"]=base["machine_due_date"]
            base["due_date_source"]=base.get("machine_due_date_source")
            if base.get("machine_date_confirmation_required"):
                base["date_confirmation_required"]=True
            else:
                base.pop("date_confirmation_required",None)
        if "machine_severity" in base:
            base["severity"]=base["machine_severity"]
            base["severity_source"]=base.get("machine_severity_source")
        base.pop("status_source", None)
        base.pop("status_set_at", None)
        if base.get("severity_source")=="user":base.pop("severity_source",None)
        if base.get("due_date_source")=="user":base.pop("due_date_source",None)
        machine_rows.append(base)
    effective = apply_user_annotations(machine_rows, state, now_ts=generated)
    for row in effective:
        if str(row.get("status") or "").upper() != "WAITING":
            row.pop("waiting_context", None)
    information=apply_user_annotations(payload.get("informational") or [],state,now_ts=generated)
    # Explicit user tracking is a personal commitment, even when the source
    # itself is optional. Never silently demote an active user decision.
    references=[]
    for row in information:
        entry=(state.get("obligations") or {}).get(row.get("id"))
        if explicit_tracking(entry):
            row.pop("obligation_suppressed",None)
            row["user_tracking"]=True
            effective.append(row)
        else:
            references.append(row)
    result["informational"]=references
    result["tasks"] = [x for x in effective if str(x.get("status") or "").upper() not in {"DONE", "DISMISSED"}]
    result["resolved"] = [x for x in effective if str(x.get("status") or "").upper() in {"DONE", "DISMISSED"}]
    attention = derive_attention(effective, now_ts=generated)
    result["attention"] = attention
    result["briefing"] = daily_briefing(attention)
    result["user_state_revision"] = int(state.get("revision") or 0)
    return result
