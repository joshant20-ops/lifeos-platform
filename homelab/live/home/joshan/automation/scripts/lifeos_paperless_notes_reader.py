#!/usr/bin/env python3
# ============================================================
# LIFEOS INSTALLER SAFETY HEADER
# Script: scripts/lifeos_paperless_notes_reader.py
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
import json, time, subprocess, re, html

AUTO = Path("/home/joshan/automation")
LOGS = AUTO / "logs"
HA = Path("/opt/stacks/homeassistant/config")
LOVELACE = HA / ".storage" / "lovelace.dashboard_homelab"

OUT = LOGS / "paperless_notes_facts.json"
SUMMARY = LOGS / "paperless_notes_summary.json"

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def esc(x):
    return html.escape(str(x)) if x is not None else ""

def fetch_docs_with_notes():
    code = r'''
import json
from documents.models import Document

def safe_notes(d):
    parts = []
    try:
        raw = getattr(d, "notes", None)
        if isinstance(raw, str):
            parts.append(raw)
        elif hasattr(raw, "all"):
            for n in raw.all():
                parts.append(str(n))
    except Exception as e:
        parts.append("")
    try:
        raw = getattr(d, "note", "")
        if isinstance(raw, str):
            parts.append(raw)
    except Exception:
        pass
    return "\n".join([p for p in parts if p])

docs = []
for d in Document.objects.all().order_by("-created")[:500]:
    notes = safe_notes(d)
    docs.append({
        "id": int(d.id),
        "title": str(d.title or ""),
        "created": d.created.isoformat() if d.created else None,
        "document_type": str(d.document_type) if d.document_type else "",
        "correspondent": str(d.correspondent) if d.correspondent else "",
        "tags": [str(t) for t in d.tags.all()],
        "notes": notes
    })
print(json.dumps(docs))
'''
    proc = subprocess.run(
        ["docker", "exec", "paperless-paperless-1", "python3", "manage.py", "shell", "-c", code],
        capture_output=True,
        text=True,
        timeout=180
    )
    if proc.returncode != 0:
        return [], proc.stderr

    txt = proc.stdout.strip()
    start = txt.find("[")
    end = txt.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(txt[start:end+1]), ""
        except Exception as e:
            return [], f"Could not parse JSON from Paperless notes output: {e}\n{txt[:500]}"
    return [], f"No JSON array found in Paperless notes output\n{txt[:500]}"

def classify_from_notes(doc):
    notes = (doc.get("notes") or "").strip()
    if not notes:
        return None

    hay = " ".join([
        notes,
        doc.get("title", ""),
        " ".join(doc.get("tags", [])),
        doc.get("document_type", "")
    ]).lower()

    if any(x in hay for x in ["mot", "mot test", "test certificate", "registration number"]) and any(x in hay for x in ["bike", "motorbike", "vehicle", "registration"]):
        kind = "vehicle_mot"
        section = "Vehicles"
        title = "Motorbike MOT"
    elif any(x in hay for x in ["landlord insurance", "residential landlord", "certificate of insurance", "policy schedule", "churchill", "simply business"]):
        kind = "landlord_insurance"
        section = "Insurance / Cover"
        title = "Landlord / house insurance"
    elif any(x in hay for x in ["home emergency", "247 home rescue"]):
        kind = "home_emergency_cover"
        section = "Insurance / Cover"
        title = "Home emergency cover"
    elif any(x in hay for x in ["bupa", "blua", "digital gp"]):
        kind = "health_benefit"
        section = "Insurance / Cover"
        title = "Health / Bupa benefit"
    else:
        return None

    years = [int(y) for y in re.findall(r"\b(20[0-9]{2})\b", hay)]
    latest_year = max(years) if years else None

    return {
        "document_id": doc.get("id"),
        "document_title": doc.get("title"),
        "document_type": doc.get("document_type"),
        "tags": doc.get("tags", []),
        "kind": kind,
        "target_section": section,
        "target_title": title,
        "latest_year_seen": latest_year,
        "current_hint": bool(latest_year and latest_year >= 2025),
        "notes_excerpt": notes[:1200],
        "source": "paperless_notes_reader_v1",
        "notes_are_read_only": True,
        "state_mutation": False
    }

docs, err = fetch_docs_with_notes()

facts = []
for doc in docs:
    item = classify_from_notes(doc)
    if item:
        facts.append(item)

facts.sort(key=lambda x: (x["target_title"], -(x["latest_year_seen"] or 0), x["document_id"] or 0))

summary = {
    "ok": not bool(err),
    "generated_time": int(time.time()),
    "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
    "documents_checked": len(docs),
    "documents_with_notes": sum(1 for d in docs if (d.get("notes") or "").strip()),
    "facts_found": len(facts),
    "error": err,
    "source_priority": "paperless_notes_only",
    "notes_are_read_only": True,
    "state_mutation": False,
    "by_kind": {}
}

for f in facts:
    summary["by_kind"][f["kind"]] = summary["by_kind"].get(f["kind"], 0) + 1

write_json(OUT, {"schema": "paperless_notes_facts_v1", "facts": facts})
write_json(SUMMARY, summary)
write_json(HA / "paperless_notes_facts.json", {"schema": "paperless_notes_facts_v1", "facts": facts})
write_json(HA / "paperless_notes_summary.json", summary)

lines = [
    "### Paperless Notes Facts",
    "",
    "This card reads the existing Paperless notes created by PA. Notes are treated as read-only interpreted data.",
    "",
    f"- Documents checked: `{summary['documents_checked']}`",
    f"- Documents with notes: `{summary['documents_with_notes']}`",
    f"- Facts found from notes: `{summary['facts_found']}`",
    "",
]

if not facts:
    lines.append("✅ No note-derived facts found yet.")
else:
    current_target = None
    for f in facts[:30]:
        if f["target_title"] != current_target:
            current_target = f["target_title"]
            lines.append(f"## {esc(current_target)}")
            lines.append("")
        lines += [
            f"### {esc(f.get('document_title') or 'Untitled document')}",
            f"- Document: `paperless_document_id:{f.get('document_id')}`",
            f"- Type: `{esc(f.get('kind'))}`",
            f"- Latest year seen: `{esc(f.get('latest_year_seen') or 'unknown')}`",
            f"- Current hint: `{esc(f.get('current_hint'))}`",
            "",
            "**Notes excerpt:**",
            "",
            f"> {esc(f.get('notes_excerpt','')).replace(chr(10), '<br>')}",
            "",
            "---"
        ]

md = "\n".join(lines) + "\n"

(HA / "www" / "lifeos").mkdir(parents=True, exist_ok=True)
(HA / "www" / "lifeos" / "paperless_notes_facts.md").write_text(md)

lovelace = read_json(LOVELACE, None)
if lovelace:
    views = lovelace.setdefault("data", {}).setdefault("config", {}).setdefault("views", [])
    target = next((v for v in views if v.get("path") == "important-information"), None)
    if target:
        cards = target.setdefault("cards", [])
        cards = [c for c in cards if c.get("title") != "Paperless Notes Facts"]
        cards.insert(1, {
            "type": "markdown",
            "title": "Paperless Notes Facts",
            "content": md
        })
        target["cards"] = cards
        LOVELACE.write_text(json.dumps(lovelace, indent=2, sort_keys=False) + "\n")

print(json.dumps(summary, indent=2, sort_keys=True))
raise SystemExit(0 if not err else 1)
