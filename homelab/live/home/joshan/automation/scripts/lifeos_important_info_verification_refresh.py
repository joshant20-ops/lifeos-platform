# ============================================================
# LIFEOS INSTALLER SAFETY HEADER
# Script: scripts/lifeos_important_info_verification_refresh.py
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

BACKUP = AUTO / "backups" / f"verification_state_v1_{time.strftime('%Y%m%d_%H%M%S')}"

INFO = STATE / "important_information.json"

VALID_STATUSES = {
    "unknown",
    "unverified",
    "partially_verified",
    "verified",
    "conflicting",
    "stale",
    "expired"
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

def default_verification(item):
    confidence = item.get("confidence", "unknown")

    if confidence in {"missing", "planned"}:
        status = "unknown"
    elif confidence in {"user-stated", "synthetic_test"}:
        status = "unverified"
    else:
        status = "unverified"

    return {
        "status": status,
        "last_verified_time": None,
        "verification_method": None,
        "stale_after_days": 365,
        "conflicting_evidence": [],
        "evidence_refs": [],
        "human_verified": False
    }

def normalize_info(data):
    changed = 0

    for sec in data.get("sections", []):
        for item in sec.get("items", []):

            if "verification" not in item:
                item["verification"] = default_verification(item)
                changed += 1

            v = item["verification"]

            if v.get("status") not in VALID_STATUSES:
                v["status"] = "unknown"
                changed += 1

            v.setdefault("last_verified_time", None)
            v.setdefault("verification_method", None)
            v.setdefault("stale_after_days", 365)
            v.setdefault("conflicting_evidence", [])
            v.setdefault("evidence_refs", [])
            v.setdefault("human_verified", False)

    data["verification_schema"] = "verification_state_v1"
    data["verification_updated_time"] = int(time.time())

    return changed

def build_summary(data):
    counts = {k: 0 for k in VALID_STATUSES}

    for sec in data.get("sections", []):
        for item in sec.get("items", []):
            status = (
                item.get("verification", {})
                .get("status", "unknown")
            )
            counts[status] = counts.get(status, 0) + 1

    return {
        "generated_time": int(time.time()),
        "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
        "verification_schema": "verification_state_v1",
        "counts": counts,
        "needs_review_count": (
            counts.get("unknown", 0)
            + counts.get("unverified", 0)
            + counts.get("conflicting", 0)
            + counts.get("stale", 0)
        ),
        "status": (
            "needs_review"
            if (
                counts.get("unknown", 0)
                + counts.get("unverified", 0)
                + counts.get("conflicting", 0)
                + counts.get("stale", 0)
            ) > 0
            else "ok"
        )
    }

def render_verification_md(data):
    out = ["### Verification State Summary\n"]

    summary = build_summary(data)

    out.append(f"- Overall status: `{esc(summary['status'])}`")
    out.append(f"- Needs review: `{summary['needs_review_count']}`")
    out.append("")

    counts = summary["counts"]

    for k in sorted(counts):
        out.append(f"- {k.replace('_',' ').title()}: `{counts[k]}`")

    out.append("")
    out.append("## Needs Verification\n")

    found = False

    for sec in data.get("sections", []):
        for item in sec.get("items", []):

            v = item.get("verification", {})
            status = v.get("status", "unknown")

            if status in {
                "unknown",
                "unverified",
                "conflicting",
                "stale"
            }:
                found = True

                out += [
                    f"### {esc(item.get('title','Untitled'))}",
                    f"- Section: `{esc(sec.get('section','unknown'))}`",
                    f"- Verification status: `{esc(status)}`",
                    f"- Confidence: `{esc(item.get('confidence','unknown'))}`",
                    f"- Source: `{esc(item.get('source','unknown'))}`",
                    f"- Needs document evidence: `{esc(item.get('needs_document_evidence',False))}`",
                    "---"
                ]

    if not found:
        out.append("✅ No items currently require verification review.\n")

    return "\n".join(out) + "\n"

BACKUP.mkdir(parents=True, exist_ok=True)

for p in [INFO, LOVELACE, PKG]:
    if p.exists():
        shutil.copy2(p, BACKUP / p.name)

data = read_json(INFO, {})
if not isinstance(data, dict):
    raise SystemExit("important_information.json invalid")

changed = normalize_info(data)

summary = build_summary(data)

write_json(INFO, data)

write_json(LOGS / "important_information_verification_summary.json", summary)
write_json(HA / "important_information_verification_summary.json", summary)

md = render_verification_md(data)

(HA / "www" / "lifeos").mkdir(parents=True, exist_ok=True)
(HA / "www" / "lifeos" / "important_information_verification.md").write_text(md)

# MQTT owns Home Assistant scalar state transport.
# Home Assistant owns dashboard presentation.

print(json.dumps({
    "ok": True,
    "backup": str(BACKUP),
    "verification_schema": "verification_state_v1",
    "items_updated": changed,
    "summary": str(HA / "important_information_verification_summary.json"),
    "markdown": str(HA / "www/lifeos/important_information_verification.md"),
    "needs_review_count": summary["needs_review_count"]
}, indent=2))

# LIFEOS_NATIVE_STATE_PUBLISHER_V1
try:
    _proposal_summary = read_json(
        HA / "important_information_proposal_summary.json",
        {}
    )
    _verification_summary = read_json(
        HA / "important_information_verification_summary.json",
        {}
    )
    _counts = _verification_summary.get("counts", {})

    _native_state = {
        "important_info_pending_proposals":
            _proposal_summary.get("pending_count", 0),
        "important_info_proposal_status":
            _proposal_summary.get("status", "unknown"),
        "verification_status":
            _verification_summary.get("status", "unknown"),
        "verification_needs_review":
            _verification_summary.get("needs_review_count", 0),
        "verification_conflicting":
            _counts.get("conflicting", 0),
        "verification_stale":
            _counts.get("stale", 0),
        "verification_unknown":
            _counts.get("unknown", 0),
        "verification_unverified":
            _counts.get("unverified", 0),
    }

    _native_path = (
        HA / "www" / "lifeos" /
        "important_info_native_state.json"
    )
    _native_path.parent.mkdir(parents=True, exist_ok=True)
    _native_path.write_text(
        json.dumps(_native_state, separators=(",", ":")) + "\n"
    )
except Exception as _native_exc:
    raise SystemExit(
        f"native HA state publication failed: {_native_exc}"
    )
