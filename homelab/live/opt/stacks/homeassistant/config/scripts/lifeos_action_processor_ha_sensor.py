#!/usr/bin/env python3
import json
import sys
from pathlib import Path

STATE = Path("/config/lifeos_action_processor_state.json")

def read():
    try:
        return json.loads(STATE.read_text()) if STATE.exists() else {}
    except Exception:
        return {}

def main():
    key = sys.argv[1] if len(sys.argv) > 1 else ""
    d = read()
    print(d.get(key, "unknown"))

if __name__ == "__main__":
    main()
