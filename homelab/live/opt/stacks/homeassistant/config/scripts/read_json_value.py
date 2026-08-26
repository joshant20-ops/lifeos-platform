#!/usr/bin/env python3
import json
import sys
from pathlib import Path

if len(sys.argv) < 3:
    print("missing_args")
    raise SystemExit(0)

path = Path(sys.argv[1])
key = sys.argv[2]
default = sys.argv[3] if len(sys.argv) > 3 else "unknown"

try:
    data = json.loads(path.read_text())
    value = data.get(key, default)
    if isinstance(value, bool):
        print(str(value).lower())
    elif value is None:
        print(default)
    else:
        print(value)
except Exception:
    print(default)
