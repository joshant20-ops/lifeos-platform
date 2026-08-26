#!/usr/bin/env python3
import json
from pathlib import Path
p = Path("/config/network_identity_summary.json")
try:
    d = json.loads(p.read_text())
except Exception as exc:
    d = {"status":"unknown","summary":str(exc),"total_devices_seen":0,"known_devices":0,"unknown_devices":0,"missing_expected_devices":0}
print(json.dumps({
    "state": d.get("status", "unknown"),
    "summary": d.get("summary", ""),
    "total_devices_seen": d.get("total_devices_seen", 0),
    "known_devices": d.get("known_devices", 0),
    "unknown_devices": d.get("unknown_devices", 0),
    "missing_expected_devices": d.get("missing_expected_devices", 0),
    "generated_at": d.get("generated_at", ""),
}))
