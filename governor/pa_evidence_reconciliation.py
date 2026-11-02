"""Pure, rebuildable obligation reconciliation over accepted PA observations.

No models, mailbox access, persistence or task publisher. The existing PA
reconciler is the only caller allowed to apply the resulting state decisions.
An outcome relationship is deliberately weaker than an obligation identity.
"""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import re

SCHEMA = "lifeos_obligation_reconciliation_v1"
SCOPE_SCHEMA = "lifeos_obligation_scope_v1"
STATES = {"OPEN": "ACTION", "WAITING": "WAITING", "DONE": "COMPLETE"}
EXPLANATIONS = {
    "latest_accepted_observation": "The latest accepted observation for this specific obligation determines its recorded state.",
    "recorded_state_retained": "Recorded state retained; no later accepted observation resolves this specific obligation.",
    "user_override": "Your explicit status decision takes precedence over source reconciliation.",
    "information_only": "Information is retained as context and creates no obligation.",
    "scope_missing": "The accepted record does not identify a specific obligation scope.",
    "source_date_unknown": "Source chronology is not established; no state change was inferred.",
    "conflicting_observations": "Equally recent accepted observations disagree; the recorded state is retained.",
    "source_unavailable": "A supporting source is currently unavailable; the recorded state is retained.",
    "obligation_identity_ambiguous": "Related evidence was found, but it does not establish the same obligation or occurrence; the recorded state is retained.",
}


def norm(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def source_time(value):
    try:
        parsed = parsedate_to_datetime(str(value or ""))
    except (ValueError, TypeError, OverflowError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return 0
    try:
        return int(parsed.timestamp()) if parsed.tzinfo else 0
    except (ValueError, OverflowError):
        return 0


def scope(issuer, action, references=(), instance=None):
    """Snapshot the classifier's accepted action, rather than the email title."""
    if not norm(issuer) or not norm(action) or len(str(issuer)) > 200 or len(str(action)) > 400 or not isinstance(references, (list, tuple, set)) or len(references) > 20 or (instance is not None and (not isinstance(instance, str) or len(instance) > 300)):
        return None
    return {"schema": SCOPE_SCHEMA, "issuer": norm(issuer), "action": norm(action),
            "instance": str(instance or ""),
            "references": sorted({re.sub(r"[^A-Z0-9]", "", str(v).upper()) for v in references if v})}


def source_ids(row):
    values = list(row.get("source_message_ids") or []) + [row.get("email_message_id")]
    return {value for value in values if isinstance(value, str) and len(value) <= 300 and re.fullmatch(r"<[^<>\s\x00-\x1f]+>", value)}


def row_scope(row):
    return scope(row.get("counterparty"), row.get("topic"), row.get("case_reference_ids") or [], row.get("obligation_key") or row["id"])


def collect_observations(rows, available_sources=None):
    """Adapt current PA snapshots and scoped history; never reinterpret a body.

    Legacy unscoped events are counted, not assigned today's topic retroactively.
    UNKNOWN EmailOps/shadow proposals are intentionally not inputs to this API.
    """
    facts = {}
    diagnostics = {"unscoped_events": 0, "undated_observations": 0}
    for row in sorted(rows, key=lambda row: str(row["id"])):
        retained = source_ids(row)
        observations = []
        current_scope = row_scope(row)
        current_status = row.get("machine_status") or row.get("status")
        primary = row.get("email_message_id")
        if row.get("status_source") in {"user", "user_confirmation"} and not row.get("machine_status"):
            current_status = None
        # Suppression is an accepted distinction, not a successful completion.
        if not row.get("obligation_suppressed") and not row.get("completion_evidence") and current_status in STATES and primary in retained and current_scope:
            observations.append({"message_id": primary, "status": current_status,
                                 "date": row.get("updated_from_email"), "obligation_scope": current_scope,
                                 "state_reason": row.get("reason"),
                                 "basis": "accepted_snapshot"})
        for event in row.get("timeline_events") or []:
            if not isinstance(event, dict) or event.get("message_id") not in retained or event.get("evidence_only") or event.get("status") not in STATES:
                continue
            if event.get("event_kind") == "information" and event["status"] != "DONE":
                continue
            event_scope = event.get("obligation_scope")
            if not isinstance(event_scope, dict) or event_scope.get("schema") != SCOPE_SCHEMA:
                diagnostics["unscoped_events"] += 1
                continue
            observations.append({**event, "basis": "accepted_observation"})
        for observation in observations:
            value = observation.get("obligation_scope") or {}
            identity = scope(value.get("issuer"), value.get("action"), value.get("references") or [], value.get("instance"))
            if not identity:
                continue
            timestamp = source_time(observation.get("date"))
            if not timestamp:
                diagnostics["undated_observations"] += 1
                continue
            source = observation["message_id"]
            signature = (source, observation["status"], timestamp, json.dumps(identity, sort_keys=True))
            fact_id = "observation-" + hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:24]
            fact = facts.setdefault(fact_id, {"id": fact_id, "source_id": source,
                "source_date": observation["date"], "timestamp": timestamp, "state": observation["status"],
                "scope": identity, "matter_ids": [], "basis": observation["basis"],
                "state_reason": str(observation.get("state_reason") or "")[:400],
                "available": available_sources is None or source in available_sources})
            if row["id"] not in fact["matter_ids"]: fact["matter_ids"].append(row["id"])
            if observation["basis"] == "accepted_observation": fact["basis"] = "accepted_observation"
    return sorted(facts.values(), key=lambda fact: (fact["timestamp"], fact["id"])), diagnostics


def matching_rule(row, fact):
    target = row_scope(row)
    if not target or (target["issuer"], target["action"]) != (fact["scope"]["issuer"], fact["scope"]["action"]):
        return None
    left, right = set(target["references"]), set(fact["scope"]["references"])
    if left and right and not left.intersection(right):
        return None
    if row["id"] in fact["matter_ids"]:
        if fact["scope"]["instance"] and fact["scope"]["instance"] != target["instance"]:
            return None
        return "same_obligation_observation"
    if fact["scope"]["instance"] and fact["scope"]["instance"] == target["instance"]:
        return "accepted_obligation_identity"
    if fact["source_id"] in source_ids(row):
        return "candidate_obligation_identity"
    if left and left == right:
        return "candidate_obligation_identity"
    # Same company, topic or owner-linked outcome alone cannot close a task.
    return None


def reconcile(rows, user_state=None, available_sources=None):
    """One source/date/conflict policy for every free-form obligation category."""
    rows = sorted((row for row in rows if isinstance(row, dict) and row.get("id")), key=lambda row: str(row["id"]))
    facts, diagnostics = collect_observations(rows, available_sources)
    entries = (user_state or {}).get("obligations") or {}
    decisions = []
    for row in rows:
        current = row.get("machine_status") or row.get("status")
        decision = {"matter_id": row["id"], "current_state": current, "proposed_state": None,
                    "support": [], "uncertainties": [], "reason": "recorded_state_retained"}
        if (entries.get(row["id"]) or {}).get("status_override"):
            decision["reason"] = "user_override"
        elif row.get("obligation_suppressed") or current not in STATES:
            decision["reason"] = "information_only"
        elif not row_scope(row):
            decision["reason"] = "scope_missing"
            decision["uncertainties"].append("scope_missing")
        else:
            boundary = source_time(row.get("updated_from_email"))
            matches = [(fact, matching_rule(row, fact)) for fact in facts]
            matches = [(fact, rule) for fact, rule in matches if rule and fact["timestamp"] >= boundary]
            if not boundary:
                decision["reason"] = "source_date_unknown"
                decision["uncertainties"].append("source_date_unknown")
            elif matches:
                latest = max(fact["timestamp"] for fact, _ in matches)
                newest = [(fact, rule) for fact, rule in matches if fact["timestamp"] == latest]
                decision["support"] = [{**fact, "relationship": rule} for fact, rule in newest]
                if len({fact["state"] for fact, _ in newest}) > 1:
                    decision["reason"] = "conflicting_observations"
                    decision["uncertainties"].append("conflicting_observations")
                elif any(rule == "candidate_obligation_identity" for _, rule in newest):
                    decision["reason"] = "obligation_identity_ambiguous"
                    decision["uncertainties"].append("obligation_identity_ambiguous")
                elif any(not fact["available"] for fact, _ in newest):
                    decision["reason"] = "source_unavailable"
                    decision["uncertainties"].append("source_unavailable")
                else:
                    decision["reason"] = "latest_accepted_observation"
                    state = newest[0][0]["state"]
                    if latest > boundary and state != current:
                        decision["proposed_state"] = state
        decision["explanation"] = EXPLANATIONS[decision["reason"]]
        decisions.append(decision)
    return {"schema": SCHEMA, "decisions": decisions, "observations": facts,
            "counts": {**diagnostics, "matters": len(decisions), "observations": len(facts),
                       "proposed_changes": sum(bool(d["proposed_state"]) for d in decisions),
                       "uncertain": sum(bool(d["uncertainties"]) for d in decisions)}}
