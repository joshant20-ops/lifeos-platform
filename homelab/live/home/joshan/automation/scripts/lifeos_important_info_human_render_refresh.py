#!/usr/bin/env python3
# ============================================================
# LIFEOS INSTALLER SAFETY HEADER
# Script: scripts/lifeos_important_info_human_render_refresh.py
# Target device: REQUIRED — must be explicit before execution
# Execution status: BLOCKED — Engineer may propose only
# Install/apply status: BLOCKED unless Auditor + Watchman validate
# Backup: REQUIRED before any privileged/runtime/config mutation
# Rollback: REQUIRED and must be script-specific
# Bounded scope: REQUIRED — no wildcard/unbounded deletion
# Validation: REQUIRED after proposed change
# Privacy: no private raw data exposure
# Target device: Pi5 / Docker host or explicit target
# Gate: Auditor validates; Watchman approves; Engineer cannot execute
# ============================================================

from pathlib import Path
import json, time, html

AUTO = Path("/home/joshan/automation")
STATE = AUTO / "state"
HA = Path("/opt/stacks/homeassistant/config")
LOVELACE = HA / ".storage" / "lovelace.dashboard_homelab"
INFO = STATE / "important_information.json"

LABELS = {
    "missing_evidence": ("🔴", "No evidence found"),
    "evidence_found": ("🟡", "Evidence found"),
    "evidence_current": ("🟢", "Evidence current"),
    "evidence_stale": ("🟠", "Evidence may be stale"),
    "conflicting_evidence": ("🔴", "Conflicting evidence"),
    "expired": ("🔴", "Expired"),
    "not_required": ("⚪", "Evidence not required"),
}

def read_json(p, d):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d

def esc(x):
    return html.escape(str(x)) if x is not None else ""

def label(item):
    state = item.get("evidence", {}).get("state", "missing_evidence")
    return LABELS.get(state, ("⚠️", state.replace("_", " ").title()))

data = read_json(INFO, {})
lines = [
    "### Important Information",
    "",
    "This is the human-readable evidence-backed view.",
    "",
    "## Operational Summary",
    ""
]

for sec in data.get("sections", []):
    for item in sec.get("items", []):
        icon, text = label(item)
        lines.append(f"{icon} **{esc(item.get('title','Untitled'))}** — {esc(text)}")

lines += ["", "---", "", "## Details", ""]

for sec in data.get("sections", []):
    lines.append(f"## {esc(sec.get('section','Unknown'))}")
    lines.append("")
    for item in sec.get("items", []):
        icon, text = label(item)
        ev = item.get("evidence", {})
        lines.append(f"### {icon} {esc(item.get('title','Untitled'))}")
        lines.append(f"**Current info:** {esc(item.get('value',''))}")
        lines.append("")
        lines.append(f"- Evidence state: **{esc(text)}**")
        lines.append(f"- Source: **{esc(str(item.get('source','unknown')).replace('_',' ').title())}**")
        lines.append(f"- Method: `{esc(ev.get('evidence_method') or 'not linked yet')}`")
        if ev.get("notes"):
            lines.append(f"- Notes: {esc(ev.get('notes'))}")
        lines.append("")

md = "\n".join(lines) + "\n"

out = HA / "www" / "lifeos" / "important_information_human.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(md)

lovelace = read_json(LOVELACE, None)
if lovelace:
    views = lovelace.setdefault("data", {}).setdefault("config", {}).setdefault("views", [])
    target = next((v for v in views if v.get("path") == "important-information"), None)
    if target:
        for card in target.get("cards", []):
            if card.get("title") == "Human View":
                card["content"] = md
        LOVELACE.write_text(json.dumps(lovelace, indent=2, sort_keys=False) + "\n")

print(json.dumps({
    "ok": True,
    "fixed": "human_view_uses_evidence_state",
    "human_markdown": str(out),
    "backend_json_changed": False
}, indent=2))
