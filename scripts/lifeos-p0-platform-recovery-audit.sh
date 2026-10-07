#!/usr/bin/env bash
# Read-only P0 recovery audit. This script must never restart services or modify host state.
set -u

echo 'P0_AUDIT_VERSION=1'
echo 'P0_AUDIT_MUTATIONS=NONE'
echo "HOST_TIME=$(date --iso-8601=seconds 2>/dev/null || echo unavailable)"
echo "TIMEZONE=$(timedatectl show -p Timezone --value 2>/dev/null || echo unavailable)"
echo "NTP_ENABLED=$(timedatectl show -p NTP --value 2>/dev/null || echo unavailable)"
echo "NTP_SYNCHRONIZED=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unavailable)"
echo "TIMESYNCD_ACTIVE=$(systemctl is-active systemd-timesyncd.service 2>/dev/null || echo unknown)"
if [[ -e /var/lib/systemd/timesync/clock ]]; then
  echo "TIMESYNCD_SAVED_CLOCK=$(stat -c '%y' /var/lib/systemd/timesync/clock 2>/dev/null || echo unreadable)"
else
  echo 'TIMESYNCD_SAVED_CLOCK=absent'
fi

probe_unit() {
  local name="$1" unit="$2" values
  values="$(systemctl show "$unit" -p LoadState -p ActiveState -p SubState -p NRestarts --value 2>/dev/null | paste -sd, -)"
  [[ -n "$values" ]] || values=unavailable
  echo "UNIT_${name}=$values"
}
probe_unit PREDBAT predbat.service
probe_unit ENERGY_FORECAST lifeos-energy-forecast.service
probe_unit POWERDOWN lifeos-powerdown-assurance.service
probe_unit POWERDOWN_ACTIVE lifeos-powerdown-assurance-active.service
probe_unit ISSUE_QUEUE_BRIDGE lifeos-ha-issue-queue-bridge.service
probe_unit GITHUB_SYNC lifeos-github-sync.service
probe_unit TASK_RECONCILER lifeos-pa-task-reconciler.service
probe_unit SNAPSHOT_EXPORT lifeos-snapshots-export.service

if command -v docker >/dev/null 2>&1; then
  echo "PREDBAT_CONTAINER=$(docker inspect --format '{{.State.Status}},restarts={{.RestartCount}},started={{.State.StartedAt}}' predbat 2>/dev/null || echo unavailable)"
  logs="$(docker logs --since 30m predbat 2>&1 || true)"
  echo "PREDBAT_HA_INTERFACE_NOT_FOUND_30M=$(printf '%s\n' "$logs" | grep -Eic 'HA interface not found|Home Assistant.*interface.*not found' || true)"
else
  echo 'PREDBAT_CONTAINER=unavailable'
  echo 'PREDBAT_HA_INTERFACE_NOT_FOUND_30M=unavailable'
fi

if command -v curl >/dev/null 2>&1; then
  predbat_http="$(curl --silent --max-time 3 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:5052/ 2>/dev/null || true)"
  [[ -n "$predbat_http" ]] || predbat_http=000
  echo "PREDBAT_HTTP_ROOT=$predbat_http"
  energy_http="$(curl --silent --max-time 4 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8110/api/energy/current 2>/dev/null || true)"
  [[ -n "$energy_http" ]] || energy_http=000
  echo "LIFEOS_ENERGY_HTTP=$energy_http"
  gh_http="$(curl --silent --max-time 5 --output /dev/null --write-out '%{http_code}' https://api.github.com/rate_limit 2>/dev/null || true)"
  [[ -n "$gh_http" ]] || gh_http=000
  echo "GITHUB_HTTPS=$gh_http"
else
  echo 'PREDBAT_HTTP_ROOT=unavailable'
  echo 'LIFEOS_ENERGY_HTTP=unavailable'
  echo 'GITHUB_HTTPS=unavailable'
fi
if getent ahostsv4 api.github.com >/dev/null 2>&1; then
  echo 'GITHUB_DNS=PASS'
else
  echo 'GITHUB_DNS=FAIL'
fi

if command -v lifeos-secret >/dev/null 2>&1; then
  lifeos-secret exec homeassistant.long_lived_access_token HA_TOKEN python3 -c '
import json, os, urllib.error, urllib.request
url="http://127.0.0.1:8123/api/states"
req=urllib.request.Request(url, headers={"Authorization":"Bearer "+os.environ["HA_TOKEN"],"Accept":"application/json"})
try:
    with urllib.request.urlopen(req, timeout=8) as response:
        rows=json.load(response)
except urllib.error.HTTPError as exc:
    print("HA_AUTH=FAIL_HTTP"+str(exc.code))
    raise SystemExit(0)
except Exception as exc:
    print("HA_AUTH=ERROR_"+type(exc).__name__)
    raise SystemExit(0)
print("HA_AUTH=PASS")
states={row.get("entity_id"):row for row in rows if row.get("entity_id")}
wanted=[
"predbat.status","predbat.pv_power_best","predbat.load_power_best","predbat.soc_kw_best","predbat.best_export_energy",
"sensor.predbat_enphase_5731818_pv_power","sensor.predbat_enphase_5731818_load_power","sensor.predbat_enphase_5731818_soc_kw","sensor.predbat_enphase_5731818_grid_power",
"sensor.lifeos_grid_import_power","event.octopus_energy_a_8b23e5b8_octoplus_power_down_events"
]
for entity in wanted:
    row=states.get(entity)
    state=str((row or {}).get("state","missing"))
    state_class="available" if row and state not in ("unknown","unavailable") else ("unavailable" if row else "missing")
    print("HA_ENTITY="+entity+" "+state_class)
' 2>&1 || echo 'HA_AUTH=PROBE_FAILED'
else
  echo 'HA_AUTH=PROBE_TOOL_UNAVAILABLE'
fi

python3 -c '
import json, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8110/api/energy/current", timeout=4) as response:
        data=json.load(response)
    fields=("grid_import_w","house_load_w","battery_soc_percent","solar_w","retrieved_at","reading_time")
    present=[key for key in fields if key in data]
    print("LIFEOS_ENERGY_FIELDS="+",".join(present))
    print("LIFEOS_ENERGY_LOCAL_STATE=PASS")
except Exception as exc:
    print("LIFEOS_ENERGY_LOCAL_STATE=FAIL_"+type(exc).__name__)
' 2>&1

bridge_errors="$(journalctl -u lifeos-ha-issue-queue-bridge.service --since '30 minutes ago' -o cat --no-pager 2>/dev/null | grep -Eic 'QUEUE_REFRESH=FAIL|Traceback|error|failed' || true)"
echo "ISSUE_QUEUE_BRIDGE_ERROR_LINES_30M=$bridge_errors"
echo 'P0_AUDIT_RESULT=COMPLETE_READ_ONLY'
