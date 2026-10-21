#!/usr/bin/env python3
"""Expose the existing PA task projection to Home Assistant without source content."""
import html
import json
import re
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifeos_pa_user_state import apply_user_state, order_tasks_for_attention, read_user_state

TASKS = Path("/config/www/lifeos_tasks.json")
def safe_markdown(value):
    value=html.escape(str(value or "Untitled task")[:160],quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])",r"\\\1",value)


def junk_task_ids(folder):
    try:
        values = set()
        for path in Path(folder).glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            task_id = str(item.get("task_id") or "") if isinstance(item, dict) else ""
            if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", task_id):
                values.add(task_id)
        return sorted(values)[:100]
    except Exception:
        return []


def project_timeline_events(events):
    """Expose bounded event summaries without message IDs or message bodies."""
    projected = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        try:
            observed_at = int(event.get("observed_at") or 0)
        except (TypeError, ValueError):
            continue
        title = str(event.get("title") or "Email update")[:120]
        status = str(event.get("status") or "NONE").upper()
        if status not in {"OPEN", "WAITING", "DONE", "NONE"}:
            status = "NONE"
        event_kind = str(event.get("event_kind") or "obligation").lower()
        if event_kind not in {"obligation", "information"}:
            event_kind = "obligation"
        projected.append({
            "observed_at": observed_at,
            "title": title,
            "status": status,
            "event_kind": event_kind,
        })
    return projected[-20:]

def main():
    try:
        payload = apply_user_state(json.loads(TASKS.read_text()), read_user_state())
        attention = payload.get("attention") or {}
        briefing = payload.get("briefing") or {}
        if payload.get("schema") != "lifeos_tasks_v3":
            raise ValueError("schema")
        if attention.get("schema") != "lifeos_attention_projection_v1":
            raise ValueError("attention")
        counts = attention.get("counts") or {}
        if not all(isinstance(counts.get(k), int) and counts[k] >= 0 for k in (
            "needs_me", "waiting_on_others", "overdue", "upcoming",
            "recently_completed", "stale_no_progress",
        )):
            raise ValueError("counts")
        generated = int(payload.get("generated_time") or 0)
        if not generated or time.time() - generated > 7 * 3600:
            raise ValueError("stale")
        all_tasks = (payload.get("tasks") or []) + (payload.get("resolved") or [])
        all_tasks = order_tasks_for_attention(all_tasks, now_ts=generated)
        snoozed_ids = {x.get("id") for x in (attention.get("snoozed") or []) if isinstance(x, dict)}
        items = [
            {**{k: x.get(k) for k in ("id", "title", "status", "due_date", "severity", "source", "source_message_ids", "paperless_evidence", "user_comments", "user_comment_count", "snoozed_until", "status_source", "severity_source", "due_date_source")}, "timeline_events": project_timeline_events(x.get("timeline_events")), "snoozed": x.get("id") in snoozed_ids}
            for x in all_tasks if isinstance(x, dict) and x.get("id")
        ][:100]
        state = "attention" if counts["needs_me"] or counts["overdue"] else "clear"
        out = {
            "state": state,
            **counts,
            "briefing": str(briefing.get("summary") or "Briefing unavailable."),
            "items": items,
            "junk_action_pending_task_ids": junk_task_ids("/config/lifeos-pa-state/junk-requests"),
            "junk_action_failed_task_ids": junk_task_ids("/config/lifeos-pa-state/junk-requests/failed"),
            "source": "lifeos_tasks_v3",
            "generated_time": generated,
            "age_seconds": max(0, int(time.time() - generated)),
        }
    except Exception:
        out = {
            "state": "unavailable",
            "needs_me": 0,
            "waiting_on_others": 0,
            "overdue": 0,
            "upcoming": 0,
            "recently_completed": 0,
            "stale_no_progress": 0,
            "briefing": "Local PA attention is unavailable.",
            "items": [],
            "junk_action_pending_task_ids": [],
            "junk_action_failed_task_ids": [],
            "source": "lifeos_tasks_v3",
        }
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
