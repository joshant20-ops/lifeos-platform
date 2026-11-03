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
        "reason": " ".join(str(task.get("user_waiting_for") or task.get("reason") or "").split())[:240],
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

def project_reconciliation(task):
    report = task.get("evidence_reconciliation")
    if not isinstance(report, dict) or report.get("schema") != "lifeos_obligation_reconciliation_v1":
        return None
    report = {**report, "effective_state": task.get("status")}
    if str(task.get("status_source") or "").startswith("user"):
        report["effective_reason"] = "user_override"
        report["effective_explanation"] = "Your decision controls the displayed state; the accepted source evidence remains linked."
    elif task.get("completion_evidence") and task.get("status") == "DONE":
        report["effective_reason"] = "source_completion"
        report["effective_explanation"] = "Later accepted evidence completes this recorded obligation; its completion sources remain linked."
    elif task.get("obligation_suppressed") or task.get("status") in {"NONE", "DISMISSED"}:
        report["effective_reason"] = "information_only"
        report["effective_explanation"] = "This source is retained as context and creates no current obligation."
    else:
        report["effective_reason"] = report.get("reason")
        report["effective_explanation"] = report.get("explanation")
    return report


def derive_projects(rows, source_attention=None):
    """Rebuildable read model over effective PA rows; never updates task authority.

    No fuzzy/provider calls. Unspecified finite outcomes remain candidates.
    Matching proof stays local alongside existing evidence navigation.
    """
    import hashlib
    from email.utils import parseaddr
    def norm(value):
        return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))
    groups = {}
    seen = set()
    suppliers = {}
    correlation = {}
    accepted_rules = {}
    conversations = {}
    retained_sources = {mid for row in rows if isinstance(row, dict) for mid in
                        ((row.get("source_message_ids") or []) + ([row["email_message_id"]] if row.get("email_message_id") else []))}
    for row in rows:
        if not isinstance(row, dict) or not row.get("id") or row["id"] in seen:
            continue
        seen.add(row["id"])
        refs = sorted(set(str(v).upper() for v in (row.get("case_reference_ids") or []) + (row.get("verified_order_refs") or []) if v))
        party, topic = norm(row.get("counterparty")), norm(row.get("topic"))
        # A complete reference set prevents transitive bridging through an
        # ambiguous multi-reference message. Counterparty alone never joins.
        order_refs = tuple(sorted(set(row.get("verified_order_refs") or [])))
        context = project_source_context(row) or {}
        _, address = parseaddr(context.get("sender") or "")
        domain = address.lower().rpartition("@")[2]
        supplier = (address.lower() if domain in {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com"} else domain) or party
        suppliers[row["id"]] = supplier
        source_ids = set(row.get("source_message_ids") or []) | ({row["email_message_id"]} if row.get("email_message_id") else set())
        correlation[row["id"]] = [
            {"source_message_id": event["message_id"], "tracking": sorted(set(evidence_refs.get("tracking") or []))}
            for event in row.get("timeline_events") or [] if isinstance(event, dict)
            and event.get("message_id") in source_ids
            and isinstance(evidence_refs := event.get("correlation_refs"), dict)
            and isinstance(evidence_refs.get("tracking"), list)
            and all(isinstance(v, str) and re.fullmatch(r"[A-Z0-9]{10,40}", v) and any(c.isdigit() for c in v) for v in evidence_refs["tracking"])
        ]
        # The sole PA publisher already records RFC reply ancestry. Require
        # the root itself to remain in accepted sources, not a guessed subject.
        thread = row.get("thread_root_id")
        conversations[row["id"]] = [{"rule": "accepted_reply_ancestry", "root_source_message_id": thread,
                                      "source_message_ids": sorted(source_ids)}] if (
            isinstance(thread, str) and re.fullmatch(r"<[^<>\s]{1,298}>", thread)
            and thread in retained_sources and source_ids) else []
        owner_anchor = (row.get("user_project") or {}).get("anchor_id")
        named_orders = {(proof.get("supplier"), proof.get("order_ref")) for proof in row.get("verified_order_links") or []
                        if isinstance(proof, dict) and proof.get("rule") == "named_supplier_exact_order"
                        and proof.get("source_message_id") in source_ids
                        and isinstance(proof.get("supplier"), str) and proof.get("supplier")
                        and isinstance(proof.get("order_ref"), str) and re.fullmatch(r"[A-Z0-9]{4,40}", proof["order_ref"])}
        if owner_anchor:
            key, rule = ("owner", owner_anchor), "owner_confirmed_membership"
        elif len(named_orders) == 1:
            named_supplier, named_ref = next(iter(named_orders))
            key, rule = ("order", named_supplier, (named_ref,)), "named_supplier_exact_order"
        elif order_refs and supplier:
            key, rule = ("order", supplier, order_refs), "verified_supplier_order"
        elif refs:
            key, rule = ("reference", "case" if row.get("case_reference_ids") else party, tuple(refs)), "exact_reference_set"
        elif party and topic:
            key, rule = ("topic", party, topic), "exact_counterparty_topic"
        else:
            key, rule = ("matter", str(row["id"])), "accepted_matter"
        groups.setdefault(key, (rule, []))[1].append(row)
        if rule == "named_supplier_exact_order": groups[key] = (rule, groups[key][1])
        accepted_rules[row["id"]] = rule
    # Cross-company outcome edges use explicit tracking or retained reply ancestry.
    # Validate whole connected components before merging: an ambiguous bridge
    # must not cause an arbitrary partial merge dependent on input order.
    keys = sorted(groups, key=str)
    parents = {key: key for key in keys}
    def root(key):
        while parents[key] != key:
            key = parents[key]
        return key
    tokens = {}
    ambiguous = set()
    token_rules = {}
    for key, (_, members) in groups.items():
        if key[0] == "owner":
            continue  # Explicit owner membership remains pinned, never widened.
        for row in members:
            values = {v for proof in correlation[row["id"]] for v in proof["tracking"]}
            # Multiple parcels are defensible only with one explicit order.
            single_order = key[0] == "order" and len(key[2]) == 1
            if (len(values) > 1 and not single_order) or (len(set(row.get("verified_order_refs") or [])) > 1 and accepted_rules[row["id"]] != "named_supplier_exact_order"):
                ambiguous.add(key)
            for value in values:
                token = ("tracking", value)
                tokens.setdefault(token, set()).add(key)
                token_rules[token] = "verified_cross_company_tracking"
            for proof in conversations[row["id"]]:
                token = ("conversation", proof["root_source_message_id"])
                tokens.setdefault(token, set()).add(key)
                token_rules[token] = "accepted_conversation_outcome"
    for linked in tokens.values():
        ordered = sorted(linked, key=str)
        for key in ordered[1:]:
            parents[root(key)] = root(ordered[0])
    components = {}
    for key in keys:
        components.setdefault(root(key), []).append(key)
    derived = {}
    for component in components.values():
        orders = {}
        for key in component:
            for row in groups[key][1]:
                if accepted_rules[row["id"]] == "named_supplier_exact_order":
                    orders.setdefault(key[1], set()).update(key[2])
                elif suppliers[row["id"]]:
                    orders.setdefault(suppliers[row["id"]], set()).update(row.get("verified_order_refs") or [])
        # A reply chain can discuss two jobs. Conflicting accepted cases or
        # orders veto the WHOLE component, including indirect bridges.
        cases = {tuple(sorted(set(str(v).upper() for v in row.get("case_reference_ids") or [])))
                 for key in component for row in groups[key][1]
                 if row.get("case_reference_ids") and not row.get("verified_order_refs")
                 and accepted_rules[row["id"]] != "named_supplier_exact_order"}
        conflict = (any(len(values) > 1 for values in orders.values()) or len(cases) > 1
                    or any(key in ambiguous for key in component))
        if len(component) > 1 and not conflict:
            evidence = tuple(sorted(value for value, linked in tokens.items() if len(linked.intersection(component)) > 1))
            rule = ("accepted_conversation_outcome" if any(token_rules[token] == "accepted_conversation_outcome" for token in evidence)
                    else "verified_cross_company_tracking")
            identity = (("tracking", tuple(token[1] for token in evidence)) if rule == "verified_cross_company_tracking"
                        else ("conversation", evidence))
            derived[identity] = (rule, [row for key in component for row in groups[key][1]])
        else:
            for key in component:
                derived[key] = groups[key]
                if conflict:
                    ambiguous.add(key)
    groups = derived
    projects = []
    for key, (rule, members) in sorted(groups.items(), key=lambda pair: str(pair[0])):
        members = sorted(members, key=lambda row: str(row["id"]))
        buckets = {name: [] for name in ("ACTION", "WAITING", "WATCH", "INFORMATION", "COMPLETE")}
        events = {}
        provenance = []
        # Prefer accepted lifecycle history over a metadata-only fallback even
        # when another matter sharing that source sorts first.
        accepted_history = {}
        for member in members:
            retained = set(member.get("source_message_ids") or []) | ({member["email_message_id"]} if member.get("email_message_id") else set())
            for event in member.get("timeline_events") or []:
                if not isinstance(event, dict) or event.get("message_id") not in retained:
                    continue
                try:
                    int(event.get("observed_at") or 0)
                except (TypeError, ValueError):
                    continue
                old = accepted_history.get(event["message_id"])
                if old is None or (old.get("evidence_only") and not event.get("evidence_only")):
                    accepted_history[event["message_id"]] = event
        for row in members:
            status = str(row.get("status") or "").upper()
            kind = ("INFORMATION" if row.get("obligation_suppressed") or status in {"NONE", "DISMISSED"}
                    else "COMPLETE" if status == "DONE" else "WATCH" if row.get("snoozed")
                    else "ACTION" if row.get("confirmation_required") and status in {"OPEN", "WAITING"}
                    else "WAITING" if status == "WAITING" else "ACTION" if status == "OPEN" else "WATCH")
            buckets[kind].append(str(row["id"]))
            ids = sorted(set(row.get("source_message_ids") or []) | ({row["email_message_id"]} if row.get("email_message_id") else set()))
            provenance.append({"matter_id": row["id"], "rule": rule, "source_message_ids": ids,
                               "accepted_group_rule": accepted_rules[row["id"]],
                               "case_reference_ids": row.get("case_reference_ids") or [],
                               "verified_order_refs": row.get("verified_order_refs") or [],
                               "verified_order_links": row.get("verified_order_links") or [],
                               "completion_evidence": row.get("completion_evidence") or [],
                               "evidence_reconciliation": project_reconciliation(row),
                               "correlation_evidence": correlation[row["id"]],
                               "conversation_evidence": conversations[row["id"]],
                               "confirmation_ref": (row.get("user_project") or {}).get("confirmation_ref")})
            history = [accepted_history[mid] for mid in ids if mid in accepted_history]
            context = row.get("source_context") or {}
            if project_source_context(row) and context.get("subject") and not any(isinstance(e, dict) and e.get("message_id") == context["message_id"] for e in history):
                from email.utils import parsedate_to_datetime
                try:
                    sent = parsedate_to_datetime(str(context.get("sent_at") or ""))
                    timestamp = int(sent.timestamp()) if sent.tzinfo else 0
                except (TypeError, ValueError, OverflowError):
                    timestamp = 0
                history.append({"message_id": context["message_id"], "title": "Source recorded: " + str(context["subject"])[:100],
                                "status": "NONE", "event_kind": "information", "observed_at": timestamp,
                                "date": context.get("sent_at"), "time_source": "email_date" if timestamp else "unknown", "evidence_only": True})
            for event in history:
                if not isinstance(event, dict) or not event.get("message_id") or event["message_id"] not in ids:
                    continue
                try:
                    observed = int(event.get("observed_at") or 0)
                except (TypeError, ValueError):
                    continue
                prior = next((e for e in events.values() if event["message_id"] in e["source_message_ids"]), None)
                if prior:
                    if row["id"] not in prior["matter_ids"]: prior["matter_ids"].append(row["id"])
                    continue
                # Consolidate same accepted update, retain all source identities.
                signature = (str(event.get("title") or "Email update"), str(event.get("status") or "NONE"), str(event.get("event_kind") or "information"), bool(event.get("evidence_only")), event.get("time_source"))
                update = events.setdefault(signature, {"title": signature[0], "status": signature[1], "event_kind": signature[2], "observed_at": 0, "source_dates": [], "source_message_ids": [], "matter_ids": [], "evidence_only": bool(event.get("evidence_only")), "time_source": event.get("time_source")})
                update["observed_at"] = max(update["observed_at"], observed)
                for field, value in (("source_dates", event.get("date")), ("source_message_ids", event["message_id"]), ("matter_ids", row["id"])):
                    if value and value not in update[field]: update[field].append(value)
        timeline = sorted(events.values(), key=lambda event: (event["observed_at"], event["title"]))
        attention = next((name for name in ("ACTION", "WAITING", "WATCH") if buckets[name]), "INFORMATION" if buckets["INFORMATION"] else "COMPLETE")
        anchors = [row for row in members if (row.get("user_project") or {}).get("source") == "user" and (row.get("user_project") or {}).get("outcome")]
        owner_anchor = key[1] if key[0] == "owner" else None
        anchor = next((row for row in members if row["id"] == owner_anchor), anchors[0] if anchors else members[0])
        metadata = anchor.get("user_project") or {}
        outcome = metadata.get("outcome")
        outcome_conflict = len({row["user_project"]["outcome"] for row in anchors}) > 1
        by_id = {str(row["id"]): row for row in members}
        def summary(ids, field):
            values = []
            questions = {
                "source_unavailable": "Review a recorded item whose original source could not be retrieved.",
                "optional_commitment": "Confirm whether to track the proposed commitment.",
                "past_event_status": "Review whether the past event still requires a response.",
            }
            for mid in ids:
                row = by_id[mid]
                question = questions.get(row.get("confirmation_required")) if field == "next_step" else None
                value = question or (row.get("user_waiting_for") if field == "waiting_for" else None) or (project_source_context(row) or {}).get(field) or row.get("reason") or ("Action details are not recorded; review the linked source." if field == "next_step" else "The expected next event is not recorded.")
                values.append(str(value)[:400])
            return list(dict.fromkeys(values))
        topic = str(members[0].get("topic") or "")
        party_name = str(members[0].get("counterparty") or "")
        if key[0] == "order" or norm(topic) in {"order confirmation", "order confirmed", "order update"}:
            display_name = (party_name + " order").strip() if party_name else members[0].get("title")
        else:
            display_name = topic or members[0].get("title")
        projects.append({"id": "project-" + hashlib.sha256(json.dumps(("user", owner_anchor or anchor["id"]) if anchors or owner_anchor else key).encode()).hexdigest()[:20],
                         "name": outcome or display_name or "Source matter",
                         "anchor_matter_id": anchor["id"], "outcome_source": "user" if outcome else None,
                         "intended_outcome": outcome, "lifecycle": "candidate" if not outcome or outcome_conflict else metadata.get("state", "active"),
                         "attention": attention, "buckets": buckets, "matter_ids": list(by_id),
                         "next_action": summary(buckets["ACTION"], "next_step"),
                         "waiting_on": summary(buckets["WAITING"], "waiting_for"),
                         "open_count": sum(len(buckets[name]) for name in ("ACTION", "WAITING", "WATCH")),
                         "completed_count": len(buckets["COMPLETE"]), "timeline": timeline,
                         "latest_update": timeline[-1] if timeline else None,
                         "evidence_reconciliation": {"schema": "lifeos_obligation_reconciliation_v1",
                             "represented_matters": sum(project_reconciliation(row) is not None for row in members),
                             "uncertain_matters": sum(bool((project_reconciliation(row) or {}).get("uncertainties")) for row in members)},
                         "uncertainties": (["Finite intended outcome not confirmed"] if not outcome else []) + (["Ambiguous correlation evidence; kept separate"] if key in ambiguous else []) + (["Conflicting owner outcome annotations; review grouping"] if outcome_conflict else []) + (["Outcome marked complete but obligations remain open"] if metadata.get("state") == "complete" and any(buckets[k] for k in ("ACTION", "WAITING", "WATCH")) else []) + (["Source evidence missing"] if any(not p["source_message_ids"] for p in provenance) else []) + (["Timeline evidence unavailable"] if not timeline else []),
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
            {**{k: x.get(k) for k in ("id", "title", "status", "due_date", "severity", "source", "source_message_ids", "paperless_evidence", "user_comments", "user_comment_count", "snoozed_until", "status_source", "severity_source", "due_date_source", "sign_in_events", "obligation_suppressed", "reason", "confirmation_required", "date_confirmation_required", "source_response_required", "user_project", "user_waiting_for", "waiting_confirmation_ref", "completion_evidence") }, "evidence_reconciliation": project_reconciliation(x), "source_context": project_source_context(x), "waiting_context": project_waiting_context(x), "timeline_events": project_timeline_events(x.get("timeline_events")), "snoozed": x.get("id") in snoozed_ids, "ai_review": task_review(str(x.get("id") or "")), "emailops_shadow_available": has_emailops_review(x.get("id"))}
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
