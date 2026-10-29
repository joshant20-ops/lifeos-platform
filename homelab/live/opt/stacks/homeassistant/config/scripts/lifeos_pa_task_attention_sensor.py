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
REVIEW_RESULTS = Path("/config/lifeos-pa-state/task-reviews")
EMAILOPS_RESULTS = Path("/config/lifeos-pa-state/emailops-shadow")


def has_emailops_review(task_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", str(task_id or "")):
        return False
    try:
        path = EMAILOPS_RESULTS / (task_id + ".json")
        return path.is_file() and time.time() - path.stat().st_mtime < 7 * 86400
    except OSError:
        return False
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


def task_review(task_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", str(task_id or "")):
        return None
    try:
        result = json.loads((REVIEW_RESULTS / (task_id + ".json")).read_text(encoding="utf-8"))
        if result.get("schema") != "lifeos_pa_task_review_v1":
            return None
        actions = result.get("recommended_actions")
        if not isinstance(actions, list) or len(actions) > 6:
            return None
        if result.get("confidence") not in {"low", "medium", "high"}:
            return None
        return {
            "analysis": str(result.get("analysis") or "")[:1600],
            "recommended_actions": [str(x)[:400] for x in actions if isinstance(x, str)],
            "response_subject": str(result.get("response_subject") or "")[:240],
            "response_body": str(result.get("response_body") or "")[:3000],
            "confidence": result["confidence"],
            "generated_at": int(result.get("generated_at") or 0),
        }
    except Exception:
        return None

def project_waiting_context(task):
    if not isinstance(task, dict) or str(task.get("status") or "").upper() != "WAITING":
        return None
    return {
        "counterparty": " ".join(str(task.get("counterparty") or "").split())[:100],
        "topic": " ".join(str(task.get("topic") or "").split())[:120],
        "reason": " ".join(str(task.get("reason") or "").split())[:240],
    }

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
        all_tasks = (payload.get("tasks") or []) + (payload.get("resolved") or []) + (payload.get("informational") or [])
        all_tasks = order_tasks_for_attention(all_tasks, now_ts=generated)
        snoozed_ids = {x.get("id") for x in (attention.get("snoozed") or []) if isinstance(x, dict)}
        projected_items = [
            {**{k: x.get(k) for k in ("id", "title", "status", "due_date", "severity", "source", "source_message_ids", "paperless_evidence", "user_comments", "user_comment_count", "snoozed_until", "status_source", "severity_source", "due_date_source", "sign_in_events", "obligation_suppressed", "reason", "confirmation_required", "date_confirmation_required", "source_response_required") }, "waiting_context": project_waiting_context(x), "timeline_events": project_timeline_events(x.get("timeline_events")), "snoozed": x.get("id") in snoozed_ids, "ai_review": task_review(str(x.get("id") or "")), "emailops_shadow_available": has_emailops_review(x.get("id"))}
            for x in all_tasks if isinstance(x, dict) and x.get("id")
        ]
        for item in projected_items:
            flag=item.get("confirmation_required")
            item["date_verified"]=item.get("due_date_source") in {"user","paperless_policy"}
            if item.get("date_confirmation_required") and not item["date_verified"]:
                item["extracted_date"]=item.get("due_date")
                item["due_date"]=None
            if flag in {"optional_commitment","source_unavailable","past_event_status"} and item.get("status") in {"OPEN","WAITING"}:
                item["original_title"]=item.get("title")
                if not item.get("date_confirmation_required"):item["extracted_date"]=item.get("due_date")
                item["title"]=("Confirm whether to track: " if flag=="optional_commitment" else "Review past event: " if flag=="past_event_status" else "Review source for: ")+str(item.get("title") or "Source matter")
                if not item["date_verified"]:item["due_date"]=None
        # Older cached cards interpret every OPEN row in items as an action.
        # Retained information must have its own channel across UI upgrades.
        items=[item for item in projected_items if not item.get("obligation_suppressed")][:100]
        reference_items=[item for item in projected_items if item.get("obligation_suppressed")][:100]
        questions=sum((x.get("confirmation_required") in {"optional_commitment","source_unavailable","past_event_status"} or any(e.get("answer")!="yes" for e in x.get("sign_in_events") or []) and not any(e.get("answer")=="no" for e in x["sign_in_events"])) and x.get("status") in {"OPEN","WAITING"} and not x.get("snoozed") and not x.get("obligation_suppressed") for x in items)
        state = "attention" if counts["needs_me"] or counts["overdue"] else "clear"
        out = {
            "state": state,
            **counts,
            "questions": questions,
            "information": len(reference_items),
            "briefing": str(briefing.get("summary") or "Briefing unavailable."),
            "items": items,
            "reference_items": reference_items,
            "total_matters": len(all_tasks),
            "junk_action_pending_task_ids": junk_task_ids("/config/lifeos-pa-state/junk-requests"),
            "junk_action_failed_task_ids": junk_task_ids("/config/lifeos-pa-state/junk-requests/failed"),
            "review_pending_task_ids": junk_task_ids("/config/lifeos-pa-state/review-requests"),
            "review_failed_task_ids": junk_task_ids("/config/lifeos-pa-state/review-requests/failed"),
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
            "reference_items": [],
            "junk_action_pending_task_ids": [],
            "junk_action_failed_task_ids": [],
            "review_pending_task_ids": [],
            "review_failed_task_ids": [],
            "source": "lifeos_tasks_v3",
        }
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
