#!/usr/bin/env python3
# ============================================================
# LIFEOS INSTALLER SAFETY HEADER
# Script: scripts/lifeos_paperless_memory_index.py
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

BASE = Path("/home/joshan/automation")
LOGS = BASE / "logs"
HA = Path("/opt/stacks/homeassistant/config")
LOVELACE = HA / ".storage" / "lovelace.dashboard_homelab"

OUT = LOGS / "paperless_memory_index.json"
SUMMARY = LOGS / "paperless_memory_index_summary.json"

def esc(x):
    return html.escape(str(x)) if x is not None else ""

def read_json(p, d):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d

def write_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

def fetch_notes():
    code = r'''
import json
from documents.models import Document, Note

rows = []
for d in Document.objects.all().order_by("id"):
    notes = []
    for n in d.notes.all().order_by("created"):
        notes.append({
            "note_id": n.id,
            "created": n.created.isoformat() if n.created else None,
            "note": str(n.note or "")
        })
    if notes:
        rows.append({
            "document_id": d.id,
            "title": str(d.title or ""),
            "document_type": str(d.document_type) if d.document_type else "",
            "tags": [str(t) for t in d.tags.all()],
            "notes": notes
        })
print(json.dumps(rows))
'''
    proc = subprocess.run(
        ["docker", "exec", "paperless-paperless-1", "python3", "manage.py", "shell", "-c", code],
        capture_output=True, text=True, timeout=180
    )
    if proc.returncode != 0:
        return [], proc.stderr

    txt = proc.stdout.strip()
    a, b = txt.find("["), txt.rfind("]")
    if a >= 0 and b > a:
        return json.loads(txt[a:b+1]), ""
    return [], "No JSON array found"

rows, err = fetch_notes()

groups = {}
docs = {}

for row in rows:
    doc_id = row["document_id"]
    docs[str(doc_id)] = {
        "document_id": doc_id,
        "title": row["title"],
        "document_type": row["document_type"],
        "tags": row["tags"],
        "note_ids": [n["note_id"] for n in row["notes"]],
    }

    for n in row["notes"]:
        note = n.get("note", "")
        group_match = re.search(r"Memory group:\s*([A-Za-z0-9_\-]+)", note)
        group = group_match.group(1) if group_match else "manual_notes"
        groups.setdefault(group, {
            "group": group,
            "document_ids": [],
            "documents": [],
            "relationships": []
        })

        if doc_id not in groups[group]["document_ids"]:
            groups[group]["document_ids"].append(doc_id)
            groups[group]["documents"].append({
                "document_id": doc_id,
                "title": row["title"],
                "note_id": n["note_id"]
            })

        related = []
        for m in re.finditer(r"Doc\s+(\d+):\s*([^\n\r]+)", note):
            related.append({
                "document_id": int(m.group(1)),
                "title": m.group(2).strip()
            })

        if related:
            groups[group]["relationships"].append({
                "source_document_id": doc_id,
                "source_title": row["title"],
                "note_id": n["note_id"],
                "related_documents": related
            })

index = {
    "schema": "paperless_memory_index_v1",
    "generated_time": int(time.time()),
    "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
    "ok": not bool(err),
    "error": err,
    "source": "Paperless Note objects",
    "purpose": "read-only saved relationship/workflow memory for Steward and PA",
    "documents_with_notes": len(rows),
    "memory_groups": groups,
    "documents": docs,
    "state_mutation": False
}

summary = {
    "ok": index["ok"],
    "generated_time": index["generated_time"],
    "generated_iso": index["generated_iso"],
    "documents_with_notes": len(rows),
    "group_count": len(groups),
    "relationship_count": sum(len(g["relationships"]) for g in groups.values()),
    "groups": {k: len(v["document_ids"]) for k, v in groups.items()},
    "state_mutation": False,
    "error": err
}

write_json(OUT, index)
write_json(SUMMARY, summary)
write_json(HA / "paperless_memory_index.json", index)
write_json(HA / "paperless_memory_index_summary.json", summary)

lines = [
    "### Paperless Memory Index",
    "",
    "Read-only saved-state index built from Paperless notes.",
    "",
    f"- Documents with notes: `{summary['documents_with_notes']}`",
    f"- Memory groups: `{summary['group_count']}`",
    f"- Relationship entries: `{summary['relationship_count']}`",
    "",
    "This lets Steward/PA use Paperless notes as persistent relationship/workflow memory before falling back to raw Content tab evidence.",
    "",
    "## Groups",
    ""
]

for group, count in sorted(summary["groups"].items()):
    lines.append(f"- `{esc(group)}`: {count} documents")

lines.append("")

for group, g in sorted(groups.items()):
    lines.append(f"## {esc(group)}")
    for d in g["documents"][:20]:
        lines.append(f"- Doc {d['document_id']}: {esc(d['title'])} — note `{d['note_id']}`")
    lines.append("")

md = "\n".join(lines) + "\n"
(HA / "www/lifeos").mkdir(parents=True, exist_ok=True)
(HA / "www/lifeos/paperless_memory_index.md").write_text(md)

lov = read_json(LOVELACE, None)
if lov:
    views = lov.setdefault("data", {}).setdefault("config", {}).setdefault("views", [])
    target = next((v for v in views if v.get("path") == "important-information"), None)
    if target:
        cards = target.setdefault("cards", [])
        cards = [c for c in cards if c.get("title") != "Paperless Memory Index"]
        cards.insert(1, {"type": "markdown", "title": "Paperless Memory Index", "content": md})
        target["cards"] = cards
        LOVELACE.write_text(json.dumps(lov, indent=2) + "\n")

print(json.dumps(summary, indent=2, sort_keys=True))
raise SystemExit(0 if index["ok"] else 1)
