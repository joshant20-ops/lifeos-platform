# ============================================================
# LIFEOS INSTALLER SAFETY HEADER
# Script: scripts/lifeos_pa_escalation_engine.py
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
BACKUP = AUTO / "backups" / f"pa_escalation_v1_{time.strftime('%Y%m%d_%H%M%S')}"
LOVELACE = HA / ".storage" / "lovelace.dashboard_homelab"
PKG = HA / "packages" / "lifeos_pa_lifecycle.yaml"

NOW = int(time.time())

RULES = [
    {
        "name": "refund_missing_30d",
        "loop_types": ["refund", "return"],
        "statuses": ["open", "in_transit", "waiting_confirmation", "refunded"],
        "age_days": 30,
        "severity": "high",
        "message": "Refund/return loop has been open for 30+ days."
    },
    {
        "name": "parcel_stalled_14d",
        "loop_types": ["delivery", "parcel", "order"],
        "statuses": ["open", "in_transit"],
        "stale_days": 14,
        "severity": "medium",
        "message": "Delivery/order appears stalled for 14+ days."
    },
    {
        "name": "awaiting_confirmation_7d",
        "statuses": ["waiting_confirmation"],
        "stale_days": 7,
        "severity": "medium",
        "message": "Loop has been awaiting human confirmation for 7+ days."
    },
    {
        "name": "renewal_approaching_30d",
        "loop_types": ["renewal", "insurance", "subscription", "mot"],
        "statuses": ["open", "renewed"],
        "priority": "date_based",
        "severity": "medium",
        "message": "Renewal/expiry style loop needs date review."
    },
    {
        "name": "generic_stale_30d",
        "statuses": ["open", "in_transit", "waiting_confirmation"],
        "stale_days": 30,
        "severity": "low",
        "message": "Open loop has not changed for 30+ days."
    }
]

def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

def clean(x):
    return html.escape(str(x)) if x is not None else ""

def get_loops():
    raw = read_json(STATE / "open_loops.json", [])
    if isinstance(raw, dict):
        return raw.get("loops", [])
    if isinstance(raw, list):
        return raw
    return []

def days_since(ts):
    try:
        return round((NOW - int(ts)) / 86400, 1)
    except Exception:
        return 0

def match_rule(loop, rule):
    status = str(loop.get("status", "unknown"))
    loop_type = str(loop.get("loop_type", "unknown")).lower()

    if "statuses" in rule and status not in rule["statuses"]:
        return False

    if "loop_types" in rule:
        if not any(t in loop_type for t in rule["loop_types"]):
            return False

    age = days_since(loop.get("created_time", NOW))
    stale = days_since(loop.get("last_update_time", loop.get("created_time", NOW)))

    if "age_days" in rule and age < rule["age_days"]:
        return False

    if "stale_days" in rule and stale < rule["stale_days"]:
        return False

    return True

def escalation_for(loop, rule):
    age = days_since(loop.get("created_time", NOW))
    stale = days_since(loop.get("last_update_time", loop.get("created_time", NOW)))
    loop_id = loop.get("loop_id", "unknown")
    return {
        "escalation_id": f"esc_{rule['name']}_{loop_id}",
        "created_time": NOW,
        "rule": rule["name"],
        "severity": rule["severity"],
        "message": rule["message"],
        "loop_id": loop_id,
        "loop_type": loop.get("loop_type", "unknown"),
        "status": loop.get("status", "unknown"),
        "priority": loop.get("priority", "normal"),
        "summary": loop.get("summary", ""),
        "next_expected_event": loop.get("next_expected_event", ""),
        "age_days": age,
        "stale_days": stale,
        "source": "pa_escalation_engine_v1",
        "proposed_action": "create_pa_review_job",
        "state_mutation": False
    }

def render_md(escalations):
    if not escalations:
        return "### PA Escalations\n\n✅ No escalations currently active.\n"

    out = ["### PA Escalations\n"]
    for i, e in enumerate(escalations[:15], 1):
        out += [
            f"#### {i}. {clean(e.get('summary') or e.get('loop_id'))}",
            f"- Severity: `{clean(e.get('severity'))}`",
            f"- Rule: `{clean(e.get('rule'))}`",
            f"- Status: `{clean(e.get('status'))}`",
            f"- Type: `{clean(e.get('loop_type'))}`",
            f"- Age: `{clean(e.get('age_days'))}` days",
            f"- Stale: `{clean(e.get('stale_days'))}` days",
            f"- Reason: {clean(e.get('message'))}",
            f"- Proposed action: `{clean(e.get('proposed_action'))}`",
            "---"
        ]
    if len(escalations) > 15:
        out.append(f"\nShowing 15 of {len(escalations)} escalations.")
    return "\n".join(out) + "\n"

BACKUP.mkdir(parents=True, exist_ok=True)
for p in [LOVELACE, PKG, LOGS / "pa_escalations.json", HA / "pa_escalations.json"]:
    if p.exists():
        shutil.copy2(p, BACKUP / p.name)

loops = get_loops()
escalations = []
seen = set()

for loop in loops:
    if not isinstance(loop, dict):
        continue
    for rule in RULES:
        if match_rule(loop, rule):
            e = escalation_for(loop, rule)
            if e["escalation_id"] not in seen:
                seen.add(e["escalation_id"])
                escalations.append(e)

severity_rank = {"high": 0, "medium": 1, "low": 2}
escalations.sort(key=lambda e: (severity_rank.get(e["severity"], 9), -e["stale_days"], -e["age_days"]))

summary = {
    "generated_time": NOW,
    "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(NOW)),
    "status": "active" if escalations else "ok",
    "count": len(escalations),
    "high": sum(1 for e in escalations if e["severity"] == "high"),
    "medium": sum(1 for e in escalations if e["severity"] == "medium"),
    "low": sum(1 for e in escalations if e["severity"] == "low"),
    "engine": "pa_escalation_engine_v1",
    "state_mutation": False
}

write_json(LOGS / "pa_escalations.json", escalations)
write_json(LOGS / "pa_escalation_summary.json", summary)
write_json(HA / "pa_escalations.json", escalations)
write_json(HA / "pa_escalation_summary.json", summary)

md = render_md(escalations)
(HA / "www" / "lifeos").mkdir(parents=True, exist_ok=True)
(HA / "www" / "lifeos" / "pa_escalations.md").write_text(md)

# Extend HA command_line package safely
pkg_text = PKG.read_text() if PKG.exists() else "command_line:\n"
if "LifeOS PA Escalation Count" not in pkg_text:
    pkg_text += r'''

  - sensor:
      name: LifeOS PA Escalation Count
      command: "python3 - <<'PY'\nimport json\nfrom pathlib import Path\np=Path('/config/pa_escalation_summary.json')\ntry:\n d=json.loads(p.read_text()); print(d.get('count',0))\nexcept Exception:\n print(0)\nPY"
      scan_interval: 300

  - sensor:
      name: LifeOS PA High Escalations
      command: "python3 - <<'PY'\nimport json\nfrom pathlib import Path\np=Path('/config/pa_escalation_summary.json')\ntry:\n d=json.loads(p.read_text()); print(d.get('high',0))\nexcept Exception:\n print(0)\nPY"
      scan_interval: 300
'''
    PKG.write_text(pkg_text)

# Patch Lovelace PA view
data = read_json(LOVELACE, None)
if data:
    views = data.setdefault("data", {}).setdefault("config", {}).setdefault("views", [])
    target = None
    for view in views:
        if view.get("path") == "pa-lifecycle" or view.get("title") == "PA Lifecycle":
            target = view
            break
    if target is not None:
        cards = target.setdefault("cards", [])
        cards = [c for c in cards if c.get("title") not in {"Escalations", "PA Escalations"}]
        cards.insert(1, {
            "type": "markdown",
            "title": "PA Escalations",
            "content": md
        })
        target["cards"] = cards
        LOVELACE.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")

print(json.dumps({
    "ok": True,
    "backup": str(BACKUP),
    "escalation_count": len(escalations),
    "summary": str(HA / "pa_escalation_summary.json"),
    "escalations": str(HA / "pa_escalations.json"),
    "markdown": str(HA / "www" / "lifeos" / "pa_escalations.md"),
    "state_mutation": False
}, indent=2))
