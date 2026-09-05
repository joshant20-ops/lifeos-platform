#!/usr/bin/env bash
set -Eeuo pipefail

MQTT_PORT=${LIFEOS_MQTT_PORT:-1883}
PAYLOAD="$(timeout 45s mosquitto_sub -h 127.0.0.1 -p "$MQTT_PORT" -C 1 -t lifeos/tower/metrics)"
[[ -n "$PAYLOAD" ]] || { echo 'ERROR=tower_metrics_diagnostic_payload_absent'; exit 1; }
python3 - "$PAYLOAD" <<'PY'
import json, sys
p=json.loads(sys.argv[1])
disks=p.get('disks') or {}
if not isinstance(disks,dict) or not disks:
    raise SystemExit('ERROR=tower_metrics_diagnostic_no_disks')
for name in sorted(disks):
    d=disks[name] or {}
    for key in ('read_mb_s','write_mb_s'):
        value=d.get(key)
        if not isinstance(value,(int,float)):
            raise SystemExit(f'ERROR=disk_{name}_{key}_not_numeric:{value!r}')
    used=d.get('used_percent')
    print(f'TOWER_DISK_{name}_READ_MB_S={d["read_mb_s"]}')
    print(f'TOWER_DISK_{name}_WRITE_MB_S={d["write_mb_s"]}')
    print(f'TOWER_DISK_{name}_USED_PERCENT={used if isinstance(used,(int,float)) else "UNAVAILABLE"}')
    print(f'TOWER_DISK_{name}_FILESYSTEM_USAGE={"AVAILABLE" if isinstance(used,(int,float)) else "UNAVAILABLE"}')
print('TOWER_DISK_LIVE_DIAGNOSTICS=PASS')
PY
