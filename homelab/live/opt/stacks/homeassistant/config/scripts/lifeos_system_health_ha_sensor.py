#!/usr/bin/env python3
import json
from pathlib import Path

p = Path("/config/lifeos_system_health.json")

try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception as e:
    data = {
        "overall_state": "UNKNOWN",
        "label": "UNKNOWN",
        "summary": f"Failed to read LifeOS system health: {e}",
        "blockers": [],
        "warnings": ["read_failed"],
        "generated_at": "",
    }

print(json.dumps({
    "state": data.get("overall_state", "UNKNOWN"),
    "label": data.get("label", "UNKNOWN"),
    "summary": data.get("summary", ""),
    "blockers": len(data.get("blockers", [])),
    "warnings": len(data.get("warnings", [])),
    "generated_at": data.get("generated_at", ""),
}))
