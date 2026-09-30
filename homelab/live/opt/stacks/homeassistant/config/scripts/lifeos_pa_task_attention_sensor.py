#!/usr/bin/env python3
"""Expose the existing PA task projection to Home Assistant without source content."""
import html
import json
import re
import time
from pathlib import Path

TASKS = Path("/config/www/lifeos_tasks.json")
def safe_markdown(value):
    value=html.escape(str(value or "Untitled task")[:160],quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])",r"\\\1",value)

def main():
    try:
        payload = json.loads(TASKS.read_text())
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
        items = briefing.get("items") or []
        if not isinstance(items, list) or len(items) > 5:
            raise ValueError("briefing")
        state = "attention" if counts["needs_me"] or counts["overdue"] else "clear"
        out = {
            "state": state,
            **counts,
            "briefing": str(briefing.get("summary") or "Briefing unavailable."),
            "items": [
                {"title": safe_markdown(x.get("title")), "due_date": x.get("due_date")}
                for x in items if isinstance(x, dict)
            ],
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
            "source": "lifeos_tasks_v3",
        }
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))

if __name__ == "__main__":
    main()
