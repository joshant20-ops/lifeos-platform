#!/usr/bin/env python3
"""Read-only local audit of possible duplicate PA task rows.

This tool reads the private task projection and its user-state overlay. It never
prints task identifiers, message identifiers, titles, dates, comments, paths, or
field values. It does not mutate either input. It is for a local Pi terminal;
do not run it in GitHub Actions or attach its output to public issues if the
counts themselves are considered sensitive.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

TASK_STATE_DEFAULT = Path("/home/joshan/automation/state/lifeos_personal_tasks.json")
USER_STATE_DEFAULT = Path(
    "/opt/stacks/homeassistant/config/lifeos-pa-state/user_state.json"
)
TASK_SCHEMA = "lifeos_tasks_v3"
USER_SCHEMA = "lifeos_pa_user_state_v1"
MAX_INPUT_BYTES = 10 * 1024 * 1024
OVERRIDE_FIELDS = (
    "status_override",
    "severity_override",
    "due_date_override",
    "snoozed_until",
)


class AuditInputError(Exception):
    """Input failure with a fixed, non-sensitive category."""


def _read_json(path: Path, *, optional: bool = False) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        if optional:
            return None
        raise AuditInputError("INPUT_MISSING") from None
    except OSError:
        raise AuditInputError("INPUT_UNREADABLE") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise AuditInputError("INPUT_NOT_REGULAR")
        if info.st_size > MAX_INPUT_BYTES:
            raise AuditInputError("INPUT_TOO_LARGE")
        chunks = []
        remaining = MAX_INPUT_BYTES + 1
        while remaining:
            block = os.read(fd, min(65536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        if len(raw) > MAX_INPUT_BYTES:
            raise AuditInputError("INPUT_TOO_LARGE")
    finally:
        os.close(fd)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AuditInputError("INPUT_INVALID_JSON") from None


def _require(condition: bool) -> None:
    if not condition:
        raise AuditInputError("INPUT_SCHEMA_INVALID")


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _source_ids(row: dict[str, Any]) -> set[str]:
    values = set()
    for value in row.get("source_message_ids") or []:
        if isinstance(value, str) and value:
            values.add(value)
    for field in ("email_message_id",):
        value = row.get(field)
        if isinstance(value, str) and value:
            values.add(value)
    for event in row.get("timeline_events") or []:
        if isinstance(event, dict):
            value = event.get("message_id")
            if isinstance(value, str) and value:
                values.add(value)
    return values


def _case_refs(row: dict[str, Any]) -> set[str]:
    return {
        normalized
        for value in row.get("case_reference_ids") or []
        if (normalized := _norm(value))
    }


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    _require(payload.get("schema") == TASK_SCHEMA)
    rows = []
    seen_ids = set()
    for field in ("tasks", "resolved"):
        collection = payload.get(field, [])
        _require(isinstance(collection, list))
        for row in collection:
            _require(isinstance(row, dict))
            task_id = row.get("id")
            _require(isinstance(task_id, str) and bool(task_id))
            if task_id in seen_ids:
                continue
            seen_ids.add(task_id)
            rows.append(row)
    return rows


def _user_state(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"obligations": {}}
    _require(isinstance(payload, dict) and payload.get("schema") == USER_SCHEMA)
    obligations = payload.get("obligations")
    _require(isinstance(obligations, dict))
    _require(all(isinstance(key, str) and isinstance(value, dict)
                 for key, value in obligations.items()))
    return payload


def audit_payloads(task_payload: dict[str, Any], user_payload: Any) -> dict[str, int]:
    """Return only aggregate counts. No candidate identity or content is returned."""
    rows = _rows(task_payload)
    user_state = _user_state(user_payload)
    obligations = user_state["obligations"]
    task_ids = {row["id"] for row in rows}

    source_pairs = set()
    reference_pairs = set()
    topic_pairs = set()
    for index, left in enumerate(rows):
        left_id = left["id"]
        left_sources = _source_ids(left)
        left_refs = _case_refs(left)
        left_counterparty = _norm(left.get("counterparty"))
        left_topic = _norm(left.get("topic"))
        for right in rows[index + 1:]:
            right_id = right["id"]
            pair = (left_id, right_id)
            if left_sources & _source_ids(right):
                source_pairs.add(pair)
            if left_refs & _case_refs(right):
                reference_pairs.add(pair)
            if (
                left_counterparty
                and left_counterparty == _norm(right.get("counterparty"))
                and left_topic
                and left_topic == _norm(right.get("topic"))
            ):
                topic_pairs.add(pair)

    candidates = source_pairs | reference_pairs | topic_pairs
    with_user_state = {
        pair for pair in candidates
        if pair[0] in obligations or pair[1] in obligations
    }
    conflicts = set()
    for pair in candidates:
        left_overlay = obligations.get(pair[0], {})
        right_overlay = obligations.get(pair[1], {})
        for field in OVERRIDE_FIELDS:
            left_value = left_overlay.get(field)
            right_value = right_overlay.get(field)
            if left_value not in (None, "") and right_value not in (None, ""):
                if left_value != right_value:
                    conflicts.add(pair)
                    break

    return {
        "tasks": len(rows),
        "candidate_pairs": len(candidates),
        "shared_source_pairs": len(source_pairs),
        "case_reference_pairs": len(reference_pairs),
        "counterparty_topic_pairs": len(topic_pairs),
        "candidate_pairs_with_user_state": len(with_user_state),
        "candidate_pairs_with_override_conflicts": len(conflicts),
        "orphan_user_state_entries": len(set(obligations) - task_ids),
    }


def render_result(counts: dict[str, int]) -> str:
    fields = (
        ("TASKS", "tasks"),
        ("CANDIDATE_PAIRS", "candidate_pairs"),
        ("SHARED_SOURCE_PAIRS", "shared_source_pairs"),
        ("CASE_REFERENCE_PAIRS", "case_reference_pairs"),
        ("COUNTERPARTY_TOPIC_PAIRS", "counterparty_topic_pairs"),
        ("CANDIDATE_PAIRS_WITH_USER_STATE", "candidate_pairs_with_user_state"),
        ("CANDIDATE_PAIRS_WITH_OVERRIDE_CONFLICTS", "candidate_pairs_with_override_conflicts"),
        ("ORPHAN_USER_STATE_ENTRIES", "orphan_user_state_entries"),
    )
    lines = [
        "PA_DUPLICATE_AUDIT_RESULT=PASS",
        "PA_DUPLICATE_AUDIT_SCHEMA=lifeos_pa_duplicate_audit_v1",
    ]
    lines.extend(f"PA_DUPLICATE_AUDIT_{label}={counts[key]}" for label, key in fields)
    lines.append("PA_DUPLICATE_AUDIT_READ_ONLY=YES")
    return "\n".join(lines)


def run(task_path: Path, user_path: Path) -> str:
    task_payload = _read_json(task_path)
    _require(isinstance(task_payload, dict))
    user_payload = _read_json(user_path, optional=True)
    counts = audit_payloads(task_payload, user_payload)
    return render_result(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-state", type=Path, default=TASK_STATE_DEFAULT)
    parser.add_argument("--user-state", type=Path, default=USER_STATE_DEFAULT)
    args = parser.parse_args(argv)
    try:
        print(run(args.task_state, args.user_state))
        return 0
    except AuditInputError as exc:
        print("PA_DUPLICATE_AUDIT_RESULT=FAIL")
        print(f"PA_DUPLICATE_AUDIT_ERROR={exc}")
        print("PA_DUPLICATE_AUDIT_READ_ONLY=YES")
        return 2
    except Exception:
        print("PA_DUPLICATE_AUDIT_RESULT=FAIL")
        print("PA_DUPLICATE_AUDIT_ERROR=UNEXPECTED")
        print("PA_DUPLICATE_AUDIT_READ_ONLY=YES")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
