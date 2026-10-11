#!/usr/bin/env python3
"""Fixed, root-only Home Assistant check and Tower power-on action."""
from __future__ import annotations

import os
import subprocess
import sys

SECRET = "/usr/local/sbin/lifeos-secret"
SECRET_NAME = "homeassistant.long_lived_access_token"
CHECK_SCRIPT = """import os,urllib.request
headers={\"Authorization\":\"Bearer \"+os.environ[\"HA_TOKEN\"],\"Accept\":\"application/json\"}
request=urllib.request.Request(\"http://127.0.0.1:8123/api/states/switch.z97_power\",headers=headers)
with urllib.request.urlopen(request,timeout=10) as response:
    assert response.status==200
print(\"HA_SWITCH_ENTITY=PASS\")
"""
WAKE_SCRIPT = """import json,os,urllib.request
request=urllib.request.Request(\"http://127.0.0.1:8123/api/services/switch/turn_on\",data=json.dumps({\"entity_id\":\"switch.z97_power\"}).encode(),headers={\"Authorization\":\"Bearer \"+os.environ[\"HA_TOKEN\"],\"Content-Type\":\"application/json\",\"Accept\":\"application/json\"},method=\"POST\")
with urllib.request.urlopen(request,timeout=15) as response:
    assert response.status==200
print(\"HA_SWITCH_ACTION=PASS\")
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if os.geteuid() != 0:
        print("lifeos-ai-ha-wake requires root", file=sys.stderr)
        return 77
    if not args:
        script = WAKE_SCRIPT
    elif args == ["--check"]:
        script = CHECK_SCRIPT
    else:
        print("usage: lifeos-ai-ha-wake [--check]", file=sys.stderr)
        return 64
    subprocess.run(
        [SECRET, "exec", SECRET_NAME, "HA_TOKEN", "/usr/bin/python3", "-c", script],
        check=True,
        timeout=25,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
