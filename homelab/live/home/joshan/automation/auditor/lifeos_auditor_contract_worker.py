#!/usr/bin/env python3
from pathlib import Path
import json, time, subprocess

BASE = Path("/home/joshan/automation")
VALIDATOR = BASE / "contracts/lifeos_file_contract_validator.py"
OUT = BASE / "logs/auditor_contract_results.jsonl"
LATEST = BASE / "state/auditor_contract_latest.json"

def main():
    started = int(time.time())

    p = subprocess.run(
        ["python3", str(VALIDATOR)],
        capture_output=True,
        text=True
    )

    try:
        validator_result = json.loads(p.stdout)
    except Exception:
        validator_result = {
            "ok": False,
            "problems": ["Validator output was not valid JSON"],
            "stdout": p.stdout,
            "stderr": p.stderr
        }

    result = {
        "audit_time": started,
        "auditor": "contract_auditor",
        "audit_type": "file_contract_entanglement_check",
        "status": "PASS" if validator_result.get("ok") else "FAIL",
        "entanglement_found": not validator_result.get("ok", False),
        "validator_result": validator_result
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    LATEST.parent.mkdir(parents=True, exist_ok=True)

    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")

    LATEST.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
