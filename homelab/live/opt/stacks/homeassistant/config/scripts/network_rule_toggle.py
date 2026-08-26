import json
import sys
from pathlib import Path
from datetime import datetime, UTC

RULES_FILE = Path("/home/joshan/automation/config/network_active_rules.json")

def now():
    return datetime.now(UTC).isoformat()

def load():
    return json.loads(RULES_FILE.read_text())

def save(data):
    RULES_FILE.write_text(json.dumps(data, indent=2) + "\n")

def main():
    if len(sys.argv) < 3:
        print("Usage: toggle.py <candidate_id> <on|off>")
        return

    candidate_id = sys.argv[1]
    action = sys.argv[2].lower()

    data = load()
    updated = False

    for rule in data.get("rules", []):
        if rule.get("candidate_id") != candidate_id:
            continue

        if action == "on":
            rule["enabled"] = True
            rule["enabled_at"] = now()
        elif action == "off":
            rule["enabled"] = False
            rule["disabled_at"] = now()
        else:
            print("Invalid action: use on/off")
            return

        updated = True

    save(data)

    print(f"updated={updated}")

if __name__ == "__main__":
    main()
