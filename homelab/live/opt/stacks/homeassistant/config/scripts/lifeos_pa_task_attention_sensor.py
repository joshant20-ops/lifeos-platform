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


def project_source_context(task):
    context = task.get("source_context") or {}
    ids = set(task.get("source_message_ids") or [])
    if task.get("email_message_id"):
        ids.add(task["email_message_id"])
    if not isinstance(context, dict) or not context.get("message_id") or context["message_id"] not in ids:
        return None
    return {key: " ".join(str(context.get(key) or "").split())[:limit]
            for key, limit in (("sender", 200), ("subject", 240), ("sent_at", 100),
                               ("summary", 400), ("waiting_for", 240), ("next_step", 240))}

def derive_projects(rows, source_attention=None):
    """Rebuildable read model over effective PA rows; never updates task authority.

    No fuzzy/provider calls. Unspecified finite outcomes remain candidates.
    Matching proof stays local alongside existing evidence navigation.
    """
    import hashlib
    def norm(value):
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))
    groups = {}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or row["id"] in seen:
            continue
        seen.add(row["id"])
        refs = sorted(set(str(v).upper() for v in (row.get("case_reference_ids") or []) + (row.get("verified_order_refs") or []) if v))
        party, topic = norm(row.get("counterparty")), norm(row.get("topic"))
        # A complete reference set prevents transitive bridging through an
        # ambiguous multi-reference message. Counterparty alone never joins.
        if refs:
            key, rule = ("reference", "case" if row.get("case_reference_ids") else party, tuple(refs)), "exact_reference_set"
        elif party and topic:
            key, rule = ("topic", party, topic), "exact_counterparty_topic"
        else:
            key, rule = ("matter", str(row["id"])), "accepted_matter"
        groups.setdefault(key, (rule, []))[1].append(row)
    projects = []
    for key, (rule, members) in sorted(groups.items(), key=lambda pair: str(pair[0])):
        members = sorted(members, key=lambda row: str(row["id"]))
        buckets = {name: [] for name in ("ACTION", "WAITING", "WATCH", "INFORMATION", "COMPLETE")}
        events = {}
        seen_messages = set()
        provenance = []
        for row in members:
            status = str(row.get("status") or "").upper()
            kind = ("INFORMATION" if row.get("obligation_suppressed") or status in {"NONE", "DISMISSED"}
                    else "COMPLETE" if status == "DONE" else "WATCH" if row.get("snoozed")
                    else "ACTION" if row.get("confirmation_required") and status in {"OPEN", "WAITING"}
                    else "WAITING" if status == "WAITING" else "ACTION" if status == "OPEN" else "WATCH")
            buckets[kind].append(str(row["id"]))
            ids = sorted(set(row.get("source_message_ids") or []) | ({row["email_message_id"]} if row.get("email_message_id") else set()))
            provenance.append({"matter_id": row["id"], "rule": rule, "source_message_ids": ids,
                               "case_reference_ids": row.get("case_reference_ids") or [],
                               "verified_order_refs": row.get("verified_order_refs") or []})
            for event in row.get("timeline_events") or []:
                if not isinstance(event, dict) or not event.get("message_id") or event["message_id"] not in ids or event["message_id"] in seen_messages:
                    continue
                try:
                    observed = int(event.get("observed_at") or 0)
                except (TypeError, ValueError):
                    continue
                seen_messages.add(event["message_id"])
                # Consolidate same accepted update, retain all source identities.
                signature = (str(event.get("title") or "Email update"), str(event.get("status") or "NONE"), str(event.get("event_kind") or "information"))
                update = events.setdefault(signature, {"title": signature[0], "status": signature[1], "event_kind": signature[2], "observed_at": 0, "source_dates": [], "source_message_ids": [], "matter_ids": []})
                update["observed_at"] = max(update["observed_at"], observed)
                for field, value in (("source_dates", event.get("date")), ("source_message_ids", event["message_id"]), ("matter_ids", row["id"])):
                    if value and value not in update[field]: update[field].append(value)
        timeline = sorted(events.values(), key=lambda event: (event["observed_at"], event["title"]))
        attention = next((name for name in ("ACTION", "WAITING", "WATCH") if buckets[name]), "INFORMATION" if buckets["INFORMATION"] else "COMPLETE")
        anchors = [row for row in members if (row.get("user_project") or {}).get("source") == "user"]
        anchor = anchors[0] if anchors else members[0]
        metadata = anchor.get("user_project") or {}
        outcome = metadata.get("outcome")
        outcome_conflict = len({row["user_project"]["outcome"] for row in anchors}) > 1
        by_id = {str(row["id"]): row for row in members}
        def summary(ids, field):
            return [str((project_source_context(by_id[i]) or {}).get(field) or by_id[i].get("reason") or by_id[i].get("title") or "Details unknown")[:400] for i in ids]
        projects.append({"id": "project-" + hashlib.sha256(json.dumps(("user", anchor["id"]) if anchors else key).encode()).hexdigest()[:20],
                         "name": outcome or members[0].get("topic") or members[0].get("title") or "Source matter",
                         "anchor_matter_id": anchor["id"], "outcome_source": "user" if outcome else None,
                         "intended_outcome": outcome, "lifecycle": "candidate" if not outcome or outcome_conflict else metadata.get("state", "active"),
                         "attention": attention, "buckets": buckets, "matter_ids": list(by_id),
                         "next_action": summary(buckets["ACTION"], "next_step"),
                         "waiting_on": summary(buckets["WAITING"], "waiting_for"),
                         "open_count": sum(len(buckets[name]) for name in ("ACTION", "WAITING", "WATCH")),
                         "completed_count": len(buckets["COMPLETE"]), "timeline": timeline,
                         "latest_update": timeline[-1] if timeline else None,
                         "uncertainties": (["Finite intended outcome not confirmed"] if not outcome else []) + (["Conflicting owner outcome annotations; review grouping"] if outcome_conflict else []) + (["Outcome marked complete but obligations remain open"] if metadata.get("state") == "complete" and any(buckets[k] for k in ("ACTION", "WAITING", "WATCH")) else []) + (["Source evidence missing"] if any(not p["source_message_ids"] for p in provenance) else []),
                         "provenance": provenance})
    return {"schema": "lifeos_projects_projection_v1", "projects": projects,
            "attention": {kind: [{"project_id": p["id"], "matter_id": mid} for p in projects for mid in p["buckets"][kind]] for kind in ("ACTION", "WAITING", "WATCH", "INFORMATION", "COMPLETE")},
            "recently_completed_ids": [row["id"] for row in (source_attention or {}).get("recently_completed", [])],
            "due_soon_ids": [row["id"] for row in (source_attention or {}).get("upcoming", [])]}


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
            {**{k: x.get(k) for k in ("id", "title", "status", "due_date", "severity", "source", "source_message_ids", "paperless_evidence", "user_comments", "user_comment_count", "snoozed_until", "status_source", "severity_source", "due_date_source", "sign_in_events", "obligation_suppressed", "reason", "confirmation_required", "date_confirmation_required", "source_response_required", "user_project") }, "source_context": project_source_context(x), "waiting_context": project_waiting_context(x), "timeline_events": project_timeline_events(x.get("timeline_events")), "snoozed": x.get("id") in snoozed_ids, "ai_review": task_review(str(x.get("id") or "")), "emailops_shadow_available": has_emailops_review(x.get("id"))}
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
            "projects_view": derive_projects([{**x, "snoozed": x.get("id") in snoozed_ids} for x in all_tasks], attention),
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
