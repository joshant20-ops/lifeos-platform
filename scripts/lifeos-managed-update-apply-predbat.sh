#!/usr/bin/env bash
set -Eeuo pipefail
stage=init
trap 'rc=$?; echo "MANAGED_UPDATE_ERROR_STAGE=$stage" >&2; echo "MANAGED_UPDATE_ERROR_LINE=$LINENO" >&2; echo "MANAGED_UPDATE_ERROR_RC=$rc" >&2' ERR

backup=/usr/local/sbin/lifeos-restic-backup
sanity=/opt/stacks/lifeos-energy/predbat-sanity/collector.py
sanity_export=/opt/stacks/lifeos-energy/predbat-sanity-export/latest.json
ha_config=/opt/stacks/homeassistant/config

stage=backup
echo MANAGED_UPDATE_STAGE=$stage
test -x "$backup"
"$backup"
echo MANAGED_UPDATE_BACKUP=PASS

# Do exactly what the HA Predbat Update button does. Run this inside Home
# Assistant so its existing authenticated HA context is used; LifeOS does not
# download, replace or manage Predbat application files itself.
stage=press-update
echo MANAGED_UPDATE_STAGE=$stage
docker exec homeassistant python3 - <<'PY'
import json, pathlib, urllib.request
base="http://127.0.0.1:8123"
# Home Assistant stores the browser-visible service call behind its authenticated
# API. Obtain a short-lived request context from the running HA process is not
# supported here, so fail closed unless a managed token is already injected.
import os
token=os.environ.get("LIFEOS_HA_TOKEN") or os.environ.get("HA_TOKEN")
if not token:
    raise SystemExit("managed Home Assistant API token unavailable")
headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"}
req=urllib.request.Request(base+"/api/services/update/install",
    data=json.dumps({"entity_id":"update.predbat_version"}).encode(),
    headers=headers,method="POST")
with urllib.request.urlopen(req,timeout=30) as r:
    if r.status not in (200,201):
        raise SystemExit("update.install failed: HTTP %s"%r.status)
PY
echo MANAGED_UPDATE_NATIVE_INSTALL_REQUEST=PASS

stage=sanity-service-discovery
echo MANAGED_UPDATE_STAGE=$stage
mapfile -t sanity_units < <(
  systemctl list-unit-files --type=service --no-legend |
  awk '{print $1}' |
  while read -r unit; do
    systemctl show -p ExecStart --value "$unit" 2>/dev/null | grep -Fq "$sanity" && echo "$unit" || true
  done
)
test "${#sanity_units[@]}" -eq 1
sanity_unit="${sanity_units[0]}"

stage=regression
echo MANAGED_UPDATE_STAGE=$stage
ready=false
for attempt in $(seq 1 20); do
  before_mtime=$(stat -c %Y "$sanity_export" 2>/dev/null || echo 0)
  systemctl start "$sanity_unit"
  for _ in $(seq 1 15); do
    after_mtime=$(stat -c %Y "$sanity_export" 2>/dev/null || echo 0)
    [ "$after_mtime" -gt "$before_mtime" ] && break
    sleep 1
  done
  if python3 - "$sanity_export" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
a=d.get("sanity_assessment") or {}
raise SystemExit(0 if a.get("level") in {"PASS","WATCH"} and not a.get("fail_flags") else 1)
PY
  then
    ready=true
    break
  fi
  sleep 15
done
test "$ready" = true

echo MANAGED_UPDATE_REGRESSION=PASS
echo MANAGED_UPDATE_APPLY=PASS
