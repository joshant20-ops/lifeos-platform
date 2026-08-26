#!/usr/bin/env python3
# ============================================================
# LIFEOS INSTALLER SAFETY HEADER
# Script: scripts/lifeos_evidence_link_proposals_refresh.py
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

STATE = Path("/home/joshan/automation/state/evidence_link_proposals.json")
LOGS = Path("/home/joshan/automation/logs")
HA = Path("/opt/stacks/homeassistant/config")
LOVELACE = HA / ".storage" / "lovelace.dashboard_homelab"

def read_json(p, d):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d

def write_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

def esc(x):
    return html.escape(str(x)) if x is not None else ""

def band(p):
    score = int(p.get("score") or 0)
    strong = len(p.get("strong_hits") or [])
    neg = len(p.get("negative_hits") or [])
    pa_notes = bool(p.get("pa_notes_available"))

    if p.get("test_only"):
        return "test"

    if neg >= 2 or score < 4:
        return "likely_false_positive"

    if score >= 8 and (strong >= 1 or pa_notes):
        return "high_confidence"

    if score >= 5:
        return "needs_review"

    return "likely_false_positive"

data = read_json(STATE, {
    "schema": "evidence_link_proposals_v1",
    "updated_time": int(time.time()),
    "proposals": []
})

props = data.setdefault("proposals", [])

for p in props:
    p["review_band"] = band(p)

pending = [p for p in props if p.get("status", "pending") == "pending"]

grouped = {
    "high_confidence": [],
    "needs_review": [],
    "likely_false_positive": [],
    "test": [],
}

for p in pending:
    grouped.setdefault(p.get("review_band", "needs_review"), []).append(p)

for k in grouped:
    grouped[k].sort(key=lambda p: (-(int(p.get("score") or 0)), str(p.get("target_title", "")), str(p.get("evidence_title", ""))))

summary = {
    "generated_time": int(time.time()),
    "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
    "schema": "evidence_link_proposals_v1",
    "pending_count": len(pending),
    "total_count": len(props),
    "high_confidence": len(grouped["high_confidence"]),
    "needs_review": len(grouped["needs_review"]),
    "likely_false_positive": len(grouped["likely_false_positive"]),
    "test": len(grouped["test"]),
    "status": "pending_review" if pending else "ok",
    "state_mutation": False
}

lines = [
    "### Evidence Link Proposals",
    "",
    f"- Pending: `{summary['pending_count']}`",
    f"- High confidence: `{summary['high_confidence']}`",
    f"- Needs review: `{summary['needs_review']}`",
    f"- Likely false positives hidden from main review: `{summary['likely_false_positive']}`",
    "",
]

def render_group(title, items, limit):
    out = [f"## {title}", ""]
    if not items:
        out.append("✅ None.")
        out.append("")
        return out

    for i, p in enumerate(items[:limit], 1):
        out += [
            f"### {i}. {esc(p.get('target_title','Untitled target'))}",
            f"**Evidence:** {esc(p.get('evidence_title','unknown'))}",
            "",
            f"- Proposed state: `{esc(p.get('proposed_evidence_state','unknown'))}`",
            f"- Score: `{esc(p.get('score',''))}`",
            f"- Source: `{esc(p.get('classification_source') or p.get('source','unknown'))}`",
            f"- Document: `{esc(p.get('evidence_ref','none'))}`",
            f"- Strong hits: `{esc(', '.join(p.get('strong_hits') or []))}`",
            f"- Weak hits: `{esc(', '.join(p.get('weak_hits') or []))}`",
            "---"
        ]
    if len(items) > limit:
        out.append(f"Showing {limit} of {len(items)}.")
        out.append("")
    return out

lines += render_group("🟢 High Confidence", grouped["high_confidence"], 10)
lines += render_group("🟡 Needs Review", grouped["needs_review"], 10)

if grouped["likely_false_positive"]:
    lines += [
        "## ⚪ Likely False Positives",
        "",
        f"{len(grouped['likely_false_positive'])} hidden from the main review list.",
        "They remain in JSON for audit/debug.",
        ""
    ]

md = "\n".join(lines) + "\n"

write_json(STATE, data)
write_json(LOGS / "evidence_link_proposals.json", data)
write_json(LOGS / "evidence_link_proposal_summary.json", summary)
write_json(HA / "evidence_link_proposals.json", data)
write_json(HA / "evidence_link_proposal_summary.json", summary)

(HA / "www" / "lifeos").mkdir(parents=True, exist_ok=True)
(HA / "www" / "lifeos" / "evidence_link_proposals.md").write_text(md)

lovelace = read_json(LOVELACE, None)
if lovelace:
    views = lovelace.setdefault("data", {}).setdefault("config", {}).setdefault("views", [])
    target = next((v for v in views if v.get("path") == "important-information"), None)
    if target:
        cards = target.setdefault("cards", [])
        cards = [c for c in cards if c.get("title") != "Evidence Link Proposals"]
        cards.insert(1, {
            "type": "markdown",
            "title": "Evidence Link Proposals",
            "content": md
        })
        target["cards"] = cards
        LOVELACE.write_text(json.dumps(lovelace, indent=2, sort_keys=False) + "\n")

print(json.dumps({
    "ok": True,
    "summary": summary,
    "markdown": str(HA / "www/lifeos/evidence_link_proposals.md"),
    "state_mutation": False
}, indent=2))
