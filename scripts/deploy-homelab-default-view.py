#!/usr/bin/env python3
"""Make the infrastructure Homelab view the landing view without replacing dashboard content."""
import json
import shutil
import time
from pathlib import Path

ROOT = Path("/opt/stacks/homeassistant/config/.storage")
DASH = ROOT / "lovelace.dashboard_homelab"
BACKUPS = ROOT / ".lifeos-backups"

if not DASH.is_file():
    raise SystemExit("FAIL: Homelab dashboard storage file missing")

doc = json.loads(DASH.read_text())
views = doc.get("data", {}).get("config", {}).get("views")
if not isinstance(views, list) or not views:
    raise SystemExit("FAIL: Homelab dashboard has no views")

matches = [i for i, view in enumerate(views) if isinstance(view, dict) and view.get("path") == "homelab"]
if len(matches) != 1:
    raise SystemExit(f"FAIL: expected exactly one path=homelab view, found {len(matches)}")

before = [(v.get("title"), v.get("path")) for v in views if isinstance(v, dict)]
target = views.pop(matches[0])
views.insert(0, target)
after = [(v.get("title"), v.get("path")) for v in views if isinstance(v, dict)]

# Preserve every view/card and make a rollback copy before any mutation.
BACKUPS.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y%m%d-%H%M%S")
backup = BACKUPS / f"lovelace.dashboard_homelab.before-default-view.{stamp}.json"
shutil.copy2(DASH, backup)

tmp = DASH.with_suffix(".tmp")
tmp.write_text(json.dumps(doc, indent=2) + "\n")
json.loads(tmp.read_text())
tmp.replace(DASH)

print("HOMELAB_DEFAULT_VIEW_DEPLOY=PASS")
print("BACKUP=" + str(backup))
print("BEFORE=" + repr(before))
print("AFTER=" + repr(after))
print("VIEW_COUNT=" + str(len(views)))
print("FIRST_PATH=" + str(views[0].get("path")))
