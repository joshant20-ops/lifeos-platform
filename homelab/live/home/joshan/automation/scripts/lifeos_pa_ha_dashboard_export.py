from pathlib import Path
import json, time, shutil

BASE = Path("/home/joshan/automation")
STATE = BASE / "state"
LOGS = BASE / "logs"
HA = Path("/opt/stacks/homeassistant/config")
BACKUP = BASE / "backups" / f"pa_ha_dashboard_{time.strftime('%Y%m%d_%H%M%S')}"

def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

BACKUP.mkdir(parents=True, exist_ok=True)

for p in [
    STATE / "open_loops.json",
    STATE / "pa_latest_summary.json",
    HA / "packages" / "lifeos_pa_lifecycle.yaml",
    HA / "scripts" / "lifeos_pa_lifecycle_export.py",
]:
    if p.exists():
        dest = BACKUP / p.as_posix().lstrip("/").replace("/", "__")
        shutil.copy2(p, dest)

open_loops_raw = read_json(STATE / "open_loops.json", [])
summary = read_json(STATE / "pa_latest_summary.json", {})

if isinstance(open_loops_raw, dict):
    loops = open_loops_raw.get("loops", [])
else:
    loops = open_loops_raw

now = int(time.time())

active_statuses = {"open", "in_transit", "waiting_confirmation", "renewed", "refunded"}
closed_statuses = {"closed", "cancelled", "confirmed"}

active = []
awaiting = []
needs_attention = []
recently_closed = []
overdue = []

for loop in loops:
    if not isinstance(loop, dict):
        continue

    status = loop.get("status", "unknown")
    created = int(loop.get("created_time") or now)
    updated = int(loop.get("last_update_time") or created)
    age_days = round((now - created) / 86400, 1)
    stale_days = round((now - updated) / 86400, 1)

    item = dict(loop)
    item["age_days"] = age_days
    item["stale_days"] = stale_days

    if status in active_statuses:
        active.append(item)

    if status == "waiting_confirmation" or item.get("human_confirmation_required") is True:
        awaiting.append(item)

    if stale_days >= 14 or age_days >= 30 or status in {"error", "manual_review"}:
        overdue.append(item)
        needs_attention.append(item)

    if status in {"waiting_confirmation", "manual_review", "error"}:
        needs_attention.append(item)

    if status in closed_statuses:
        closed_time = int(item.get("closed_time") or updated)
        if now - closed_time <= 14 * 86400:
            recently_closed.append(item)

def sort_key(x):
    return (x.get("priority", "normal") != "high", -x.get("stale_days", 0), -x.get("age_days", 0))

active.sort(key=sort_key)
awaiting.sort(key=sort_key)
needs_attention.sort(key=sort_key)
overdue.sort(key=sort_key)
recently_closed.sort(key=lambda x: x.get("last_update_time", 0), reverse=True)

dashboard = {
    "generated_time": now,
    "generated_iso": time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(now)),
    "counts": {
        "total_loops": len(loops),
        "active": len(active),
        "awaiting_confirmation": len(awaiting),
        "needs_attention": len(needs_attention),
        "overdue": len(overdue),
        "recently_closed": len(recently_closed),
    },
    "status": "needs_attention" if needs_attention else "ok",
    "summary": summary,
}

exports = {
    "pa_dashboard_summary.json": dashboard,
    "open_loops_active.json": active[:50],
    "open_loops_attention.json": needs_attention[:50],
    "open_loops_awaiting_confirmation.json": awaiting[:50],
    "open_loops_overdue.json": overdue[:50],
    "open_loops_recently_closed.json": recently_closed[:50],
}

for name, data in exports.items():
    write_json(LOGS / name, data)
    write_json(HA / name, data)

script = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path

base = Path("/config")
name = sys.argv[1] if len(sys.argv) > 1 else "summary"
path_map = {
    "summary": base / "pa_dashboard_summary.json",
    "active": base / "open_loops_active.json",
    "attention": base / "open_loops_attention.json",
    "awaiting": base / "open_loops_awaiting_confirmation.json",
    "overdue": base / "open_loops_overdue.json",
    "closed": base / "open_loops_recently_closed.json",
}

p = path_map.get(name, path_map["summary"])
try:
    data = json.loads(p.read_text())
except Exception:
    print("ERROR")
    raise SystemExit(0)

if name == "summary":
    print(data.get("status", "unknown").upper())
else:
    print(len(data) if isinstance(data, list) else 0)
'''
ha_script = HA / "scripts" / "lifeos_pa_lifecycle_export.py"
ha_script.parent.mkdir(parents=True, exist_ok=True)
ha_script.write_text(script)
ha_script.chmod(0o755)

package = r'''
command_line:
  - sensor:
      name: LifeOS PA Dashboard Status
      command: "python3 /config/scripts/lifeos_pa_lifecycle_export.py summary"
      scan_interval: 300

  - sensor:
      name: LifeOS PA Active Loops
      command: "python3 /config/scripts/lifeos_pa_lifecycle_export.py active"
      scan_interval: 300

  - sensor:
      name: LifeOS PA Needs Attention
      command: "python3 /config/scripts/lifeos_pa_lifecycle_export.py attention"
      scan_interval: 300

  - sensor:
      name: LifeOS PA Awaiting Confirmation
      command: "python3 /config/scripts/lifeos_pa_lifecycle_export.py awaiting"
      scan_interval: 300

  - sensor:
      name: LifeOS PA Overdue Loops
      command: "python3 /config/scripts/lifeos_pa_lifecycle_export.py overdue"
      scan_interval: 300

  - sensor:
      name: LifeOS PA Recently Closed
      command: "python3 /config/scripts/lifeos_pa_lifecycle_export.py closed"
      scan_interval: 300
'''
pkg = HA / "packages" / "lifeos_pa_lifecycle.yaml"
pkg.parent.mkdir(parents=True, exist_ok=True)
pkg.write_text(package)

print(json.dumps({
    "ok": True,
    "backup": str(BACKUP),
    "ha_package": str(pkg),
    "ha_script": str(ha_script),
    "exports": [str(HA / k) for k in exports],
}, indent=2))
