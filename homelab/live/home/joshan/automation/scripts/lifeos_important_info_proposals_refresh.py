# ============================================================
# LIFEOS INSTALLER SAFETY HEADER
# Script: scripts/lifeos_important_info_proposals_refresh.py
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
import json, time, shutil, html

AUTO = Path("/home/joshan/automation")
STATE = AUTO / "state"
LOGS = AUTO / "logs"
HA = Path("/opt/stacks/homeassistant/config")
LOVELACE = HA / ".storage" / "lovelace.dashboard_homelab"
PKG = HA / "packages" / "lifeos_pa_lifecycle.yaml"
BACKUP = AUTO / "backups" / f"important_info_proposals_v1_{time.strftime('%Y%m%d_%H%M%S')}"

PROPOSALS = STATE / "important_information_proposals.json"

DEFAULT_PROPOSALS = {
    "schema": "important_information_proposals_v1",
    "updated_time": int(time.time()),
    "proposals": []
}

def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

def esc(x):
    return html.escape(str(x)) if x is not None else ""

def render_md(data):
    proposals = data.get("proposals", [])
    pending = [p for p in proposals if p.get("status", "pending") == "pending"]

    if not pending:
        return "### Important Information Proposals\n\n✅ No pending proposed information updates.\n"

    out = ["### Important Information Proposals\n"]
    for i, p in enumerate(pending[:20], 1):
        out += [
            f"#### {i}. {esc(p.get('title', 'Untitled proposal'))}",
            f"- Section: `{esc(p.get('section', 'unknown'))}`",
            f"- Proposed value: {esc(p.get('value', ''))}",
            f"- Confidence: `{esc(p.get('confidence', 'unknown'))}`",
            f"- Source: `{esc(p.get('source', 'unknown'))}`",
            f"- Evidence: `{esc(p.get('evidence_ref', 'none'))}`",
            f"- Status: `{esc(p.get('status', 'pending'))}`",
            "---"
        ]
    if len(pending) > 20:
        out.append(f"\nShowing 20 of {len(pending)} pending proposals.")
    return "\n".join(out) + "\n"

BACKUP.mkdir(parents=True, exist_ok=True)
for p in [PROPOSALS, LOVELACE, PKG]:
    if p.exists():
        shutil.copy2(p, BACKUP / p.name)

data = read_json(PROPOSALS, DEFAULT_PROPOSALS)
if not isinstance(data, dict):
    data = DEFAULT_PROPOSALS
data.setdefault("schema", "important_information_proposals_v1")
data.setdefault("proposals", [])
data["updated_time"] = int(time.time())

write_json(PROPOSALS, data)
write_json(LOGS / "important_information_proposals.json", data)
write_json(HA / "important_information_proposals.json", data)

pending_count = sum(1 for p in data["proposals"] if p.get("status", "pending") == "pending")
summary = {
    "generated_time": int(time.time()),
    "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
    "pending_count": pending_count,
    "total_count": len(data["proposals"]),
    "status": "pending_review" if pending_count else "ok",
    "state_mutation": False
}
write_json(LOGS / "important_information_proposal_summary.json", summary)
write_json(HA / "important_information_proposal_summary.json", summary)

md = render_md(data)
(HA / "www" / "lifeos").mkdir(parents=True, exist_ok=True)
(HA / "www" / "lifeos" / "important_information_proposals.md").write_text(md)

# Add helper script for HA sensors
helper = HA / "scripts" / "lifeos_important_info_proposals.py"
helper.parent.mkdir(parents=True, exist_ok=True)
helper.write_text("""#!/usr/bin/env python3
import json, sys
from pathlib import Path

p = Path('/config/important_information_proposal_summary.json')
try:
    data = json.loads(p.read_text())
except Exception:
    print(0)
    raise SystemExit(0)

field = sys.argv[1] if len(sys.argv) > 1 else 'pending_count'
print(data.get(field, 0))
""")
helper.chmod(0o755)

# Extend package
pkg = PKG.read_text() if PKG.exists() else "command_line:\n"
if "LifeOS Important Info Pending Proposals" not in pkg:
    pkg += r'''

  - sensor:
      name: LifeOS Important Info Pending Proposals
      command: "python3 /config/scripts/lifeos_important_info_proposals.py pending_count"
      scan_interval: 300

  - sensor:
      name: LifeOS Important Info Proposal Status
      command: "python3 /config/scripts/lifeos_important_info_proposals.py status"
      scan_interval: 300
'''
    PKG.write_text(pkg)

# Patch Important Information Lovelace view
lovelace = read_json(LOVELACE, None)
if not lovelace:
    raise SystemExit("Could not read Lovelace dashboard")

views = lovelace.setdefault("data", {}).setdefault("config", {}).setdefault("views", [])
target = None
for v in views:
    if v.get("path") == "important-information" or v.get("title") == "Important Information":
        target = v
        break

if target is None:
    target = {
        "title": "Important Information",
        "path": "important-information",
        "icon": "mdi:information-outline",
        "cards": []
    }
    views.append(target)

cards = target.setdefault("cards", [])
cards = [c for c in cards if c.get("title") not in {"Important Information Proposals", "Proposal Sensors"}]
cards.insert(0, {
    "type": "entities",
    "title": "Proposal Sensors",
    "show_header_toggle": False,
    "entities": [
        "sensor.lifeos_important_info_pending_proposals",
        "sensor.lifeos_important_info_proposal_status"
    ]
})
cards.insert(1, {
    "type": "markdown",
    "title": "Important Information Proposals",
    "content": md
})
target["cards"] = cards

LOVELACE.write_text(json.dumps(lovelace, indent=2, sort_keys=False) + "\n")

print(json.dumps({
    "ok": True,
    "backup": str(BACKUP),
    "state_file": str(PROPOSALS),
    "pending_count": pending_count,
    "ha_json": str(HA / "important_information_proposals.json"),
    "summary": str(HA / "important_information_proposal_summary.json"),
    "markdown": str(HA / "www/lifeos/important_information_proposals.md"),
    "state_mutation": False
}, indent=2))
