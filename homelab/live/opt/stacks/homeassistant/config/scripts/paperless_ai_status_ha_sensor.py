#!/usr/bin/env python3
import json
from pathlib import Path
p = Path("/config/paperless_ai_status_summary.json")
try:
    d = json.loads(p.read_text())
except Exception as exc:
    d = {"status":"unknown","summary":str(exc)}
print(json.dumps({
    "state": d.get("status", "unknown"),
    "document_count": d.get("document_count", 0),
    "suggestion_count": d.get("suggestion_count", 0),
    "held_for_review": d.get("held_for_review", 0),
    "blocked": d.get("blocked", 0),
    "watchman_queue_count": d.get("watchman_queue_count", 0),
    "action_needed": d.get("action_needed", False),
    "generated_at": d.get("generated_at", ""),
}))
