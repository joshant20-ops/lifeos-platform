#!/usr/bin/env python3
"""Read-only Engineer cleanup inventory. Output is evidence, never approval."""
import json, os, stat
from pathlib import Path
PRESERVE = (".codex", ".config/gh", ".ssh", ".openhands", ".ollama", "workspace/lifeos-platform")
CANDIDATES = (".openhands.backup", ".openhands-backup", "openhands-backup", "bootstrap-backup")
def classify(home: Path) -> dict:
    items = [{"path": str(home / rel), "classification": "PRESERVE", "exists": (home / rel).exists()} for rel in PRESERVE]
    for rel in CANDIDATES:
        path = home / rel
        if path.exists():
            items.append({"path": str(path), "classification": "REVIEW_REQUIRED", "kind": "directory" if stat.S_ISDIR(path.lstat().st_mode) else "file"})
    return {"schema_version": 1, "mode": "dry-run", "automatic_deletion": "DISABLED", "safe_to_remove": [], "items": items,
            "prohibited_actions": ["apt autoremove", "docker prune", "journal vacuum", "recursive deletion"]}
if __name__ == "__main__":
    print(json.dumps(classify(Path(os.environ.get("ENGINEER_HOME", "/home/joshan"))), sort_keys=True))
