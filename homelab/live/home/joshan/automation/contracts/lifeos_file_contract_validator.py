#!/usr/bin/env python3
from pathlib import Path
import json, re, sys

BASE = Path("/home/joshan/automation")
CONTRACT = BASE / "contracts/lifeos_file_worker_contract.json"

FILES_TO_CHECK = [
    BASE / "lifeos_ask/lifeos_simple_host_loop.py",
    BASE / "queues/lifeos_pa_audit_worker.py",
    BASE / "queues/lifeos_engineer_worker.py",
]

FORBIDDEN = [
    ("Steward/Ask loop importing PA worker", "lifeos_simple_host_loop.py", r"lifeos_pa_audit_worker"),
    ("Steward/Ask loop importing Engineer worker", "lifeos_simple_host_loop.py", r"lifeos_engineer_worker"),
    ("PA worker importing Steward loop", "lifeos_pa_audit_worker.py", r"lifeos_simple_host_loop"),
    ("Engineer worker importing Watchman runtime", "lifeos_engineer_worker.py", r"watchman_.*import|import .*watchman"),
]

def main():
    problems = []

    if not CONTRACT.exists():
        problems.append(f"Missing contract: {CONTRACT}")

    for p in FILES_TO_CHECK:
        if not p.exists():
            continue

        text = p.read_text(encoding="utf-8", errors="replace")
        for label, filename, pattern in FORBIDDEN:
            if p.name == filename and re.search(pattern, text):
                problems.append(f"{label}: {p}")

    result = {
        "ok": not problems,
        "problems": problems,
        "checked_files": [str(p) for p in FILES_TO_CHECK if p.exists()],
        "contract": str(CONTRACT)
    }

    print(json.dumps(result, indent=2))
    return 1 if problems else 0

if __name__ == "__main__":
    raise SystemExit(main())
