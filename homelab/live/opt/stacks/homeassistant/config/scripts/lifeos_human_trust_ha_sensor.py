#!/usr/bin/env python3
import json
from pathlib import Path

P = Path("/config/www/lifeos/lifeos_human_trust_summary.json")

try:
    d = json.loads(P.read_text())
except Exception as e:
    d = {"overall_status": "unknown", "error": str(e)}

out = {
    "state": d.get("overall_status", "unknown"),
    "human_action_required": "yes" if d.get("human_action_required") else "no",
    "plain_english": d.get("plain_english", {}).get("is_everything_ok", "unknown"),
    "what_needs_me": "; ".join(d.get("plain_english", {}).get("what_needs_me", [])) or "Nothing",
    "what_just_happened": d.get("plain_english", {}).get("what_just_happened", "unknown"),
    "paperless_review_count": d.get("paperless", {}).get("review_count", 0),
    "watchman_queue_count": d.get("watchman", {}).get("queue_items", 0),
    "network_unknown_observe_only": d.get("network", {}).get("unknown_devices", 0),
    "network_why_ok": d.get("network", {}).get("why_ok", "unknown"),
    "paperless_why_ok": d.get("paperless", {}).get("why_ok", "unknown"),
    "watchman_why_ok": d.get("watchman", {}).get("why_ok", "unknown"),
    "priority_level": d.get("priority", {}).get("level", "unknown"),
    "priority_label": d.get("priority", {}).get("label", "unknown"),
    "priority_reason": d.get("priority", {}).get("reason", "unknown"),
    "action_processor_status": d.get("actions", {}).get("status", "unknown"),
    "action_pending_requests": d.get("actions", {}).get("pending_requests", 0),
    "action_processed_requests": d.get("actions", {}).get("processed_requests", 0),
    "frontpage_status": d.get("frontpage", {}).get("status", "unknown"),
    "frontpage_errors": "; ".join(d.get("frontpage", {}).get("errors", [])) or "none",
    "generated_at": d.get("generated_at", "unknown")
}

print(json.dumps(out))
