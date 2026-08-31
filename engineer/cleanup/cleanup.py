#!/usr/bin/env python3
"""Fail-closed cleanup planner; dry-run unless an exact apply gate is supplied."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

CATEGORIES = {"KEEP", "REVIEW", "SAFE_TO_REMOVE", "DO_NOT_TOUCH"}
PROTECTED = tuple(Path(p) for p in (
    "/home/joshan/.codex/auth.json", "/home/joshan/.config/gh", "/home/joshan/.ssh",
    "/home/joshan/.openhands", "/home/joshan/.ollama", "/usr/share/ollama",
    "/var/lib/ollama", "/home/joshan/workspace/lifeos-platform",
))


def resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def protected(path: Path) -> bool:
    candidate = resolved(path)
    for base in PROTECTED:
        guard = resolved(base)
        if candidate == guard or guard in candidate.parents or candidate in guard.parents:
            return True
    return False


def validate(plan: dict) -> list[str]:
    errors = []
    for index, entry in enumerate(plan.get("entries", [])):
        category, raw = entry.get("category"), entry.get("path", "")
        if category not in CATEGORIES:
            errors.append(f"entry {index}: invalid category")
        if not raw:
            errors.append(f"entry {index}: missing path")
        if category == "SAFE_TO_REMOVE" and (raw.startswith("apt:") or not Path(raw).is_absolute()):
            errors.append(f"entry {index}: removable target must be an absolute filesystem path")
        if category == "SAFE_TO_REMOVE" and protected(Path(raw)):
            errors.append(f"entry {index}: protected target cannot be removed: {raw}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify cleanup candidates; defaults to dry run")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="apply only SAFE_TO_REMOVE filesystem entries")
    parser.add_argument("--confirm", default="", help="must equal APPLY_SAFE_TO_REMOVE with --apply")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    errors = validate(plan)
    if errors:
        print(json.dumps({"status": "INVALID_PLAN", "errors": errors}, indent=2)); return 2
    candidates = [e for e in plan.get("entries", []) if e["category"] == "SAFE_TO_REMOVE"]
    if not args.apply:
        print(json.dumps({"status": "DRY_RUN", "would_remove": candidates,
                          "counts": {c: sum(e["category"] == c for e in plan["entries"]) for c in sorted(CATEGORIES)}}, indent=2))
        return 0
    if args.confirm != "APPLY_SAFE_TO_REMOVE":
        print("apply refused: pass --confirm APPLY_SAFE_TO_REMOVE", file=sys.stderr); return 3
    for entry in candidates:
        target = Path(entry["path"])
        if protected(target):
            print(f"protected target refused: {target}", file=sys.stderr); return 4
        if target.is_symlink() or target.is_file(): target.unlink(missing_ok=True)
        elif target.is_dir(): shutil.rmtree(target)
    print(json.dumps({"status": "APPLIED", "removed": [e["path"] for e in candidates]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
