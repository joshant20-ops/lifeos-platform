#!/usr/bin/env bash
set -Eeuo pipefail
stage=init
trap 'rc=$?; echo "MANAGED_UPDATE_ERROR_STAGE=$stage" >&2; echo "MANAGED_UPDATE_ERROR_LINE=$LINENO" >&2; echo "MANAGED_UPDATE_ERROR_RC=$rc" >&2' ERR

backup=/usr/local/sbin/lifeos-restic-backup
sanity=/opt/stacks/lifeos-energy/predbat-sanity/collector.py
sanity_export=/opt/stacks/lifeos-energy/predbat-sanity-export/latest.json

stage=backup
echo MANAGED_UPDATE_STAGE=$stage
test -x "$backup"
"$backup"
echo MANAGED_UPDATE_BACKUP=PASS

stage=press-native-update
echo MANAGED_UPDATE_STAGE=$stage
# Equivalent to pressing Update on update.predbat_version in Home Assistant.
# The Predbat container already owns the HA URL/token it uses in normal operation;
# keep that credential inside the container and let HA call Predbat's native updater.
docker exec predbat python3 - <<'PY'
import os, requests, yaml

class Loader(yaml.SafeLoader):
    pass

with open("/config/secrets.yaml", encoding="utf-8") as f:
    secrets=yaml.safe_load(f) or {}

def secret(loader,node):
    key=loader.construct_scalar(node)
    if key not in secrets:
        raise RuntimeError("Predbat secret is missing: "+key)
    return secrets[key]
Loader.add_constructor("!secret",secret)

with open("/config/apps.yaml", encoding="utf-8") as f:
    cfg=yaml.load(f,Loader=Loader) or {}
app=cfg.get("pred_bat") or next((v for v in cfg.values() if isinstance(v,dict) and v.get("class")=="PredBat"),{})
url=str(app.get("ha_url") or "").rstrip("/")
token=str(app.get("ha_key") or "")
if not url or not token:
    raise SystemExit("Predbat HA connection details unavailable")
r=requests.post(url+"/api/services/update/install",
    headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
    json={"entity_id":"update.predbat_version"},timeout=30)
r.raise_for_status()
print("MANAGED_UPDATE_NATIVE_INSTALL_REQUEST=PASS")
PY

stage=verify-native-version
echo MANAGED_UPDATE_STAGE=$stage
candidate_version=$(docker image inspect nipar44/predbat_addon:latest -f '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || true)
candidate_version="${candidate_version#v}"
test -n "$candidate_version"
matched=false
for _ in $(seq 1 60); do
  core_version=$(docker exec predbat sh -lc "cd /config && python3 -c 'import predbat; print(predbat.THIS_VERSION)'" 2>/dev/null | tail -1 || true)
  core_version="${core_version#v}"
  if [ "$core_version" = "$candidate_version" ]; then matched=true; break; fi
  sleep 5
done
test "$matched" = true
echo MANAGED_UPDATE_CORE_VERSION="$core_version"
echo MANAGED_UPDATE_NATIVE_VERSION=PASS

stage=regression
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
  then ready=true; break; fi
  sleep 15
done
test "$ready" = true

echo MANAGED_UPDATE_REGRESSION=PASS
echo MANAGED_UPDATE_APPLY=PASS
