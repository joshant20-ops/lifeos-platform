#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
SOURCE="$PLATFORM/homelab/live/mnt/docker-data/automation/repos/LifeOS-Energy"
TARGET=/mnt/docker-data/automation/repos/LifeOS-Energy
HA_SOURCE="$PLATFORM/homelab/live/opt/stacks/homeassistant/config"
HA_TARGET=/opt/stacks/homeassistant/config
BACKUP_ROOT=/var/lib/lifeos-deploy-backups
OLD_MAIN_SHA=833dea89d3e5d194c43d3e537ed88b5e11061d708cf9fd748b53e130303a159f
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$BACKUP_ROOT/energy-opportunity-api-$STAMP"
MUTATED=0

fail() { echo "ENERGY_OPPORTUNITY_API_DEPLOY=FAIL error=$1"; return 1; }
sha() { sha256sum "$1" | awk '{print $1}'; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail must_run_as_root
cd "$PLATFORM"
head_sha=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
origin_sha=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
status=$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)
[[ "$head_sha" == "$origin_sha" && -z "$status" ]] || fail repository_not_clean_origin_main
[[ -d "$TARGET/app/services" && -d "$TARGET/app/routers" ]] || fail live_energy_source_missing

new_main_sha=$(sha "$SOURCE/app/main.py")
live_main_sha=$(sha "$TARGET/app/main.py")
[[ "$live_main_sha" == "$OLD_MAIN_SHA" || "$live_main_sha" == "$new_main_sha" ]] || \
  fail live_energy_main_has_unreviewed_drift

runuser -u joshan -- /usr/bin/python3 tests/test_energy_opportunity_service.py
echo ENERGY_OPPORTUNITY_API_TESTS=PASS

mkdir -p "$BACKUP/energy/app/services" "$BACKUP/energy/app/routers" \
  "$BACKUP/ha/packages" "$BACKUP/ha/scripts" "$BACKUP/systemd"
for pair in \
  "$TARGET/app/main.py:energy/app/main.py" \
  "$TARGET/app/services/opportunities.py:energy/app/services/opportunities.py" \
  "$TARGET/app/routers/opportunities.py:energy/app/routers/opportunities.py" \
  "$HA_TARGET/packages/lifeos_energy_attention.yaml:ha/packages/lifeos_energy_attention.yaml" \
  "$HA_TARGET/scripts/lifeos_energy_attention_sensor.py:ha/scripts/lifeos_energy_attention_sensor.py" \
  "/etc/systemd/system/lifeos-energy-opportunity-attention.service:systemd/lifeos-energy-opportunity-attention.service" \
  "/etc/systemd/system/lifeos-energy-opportunity-attention.timer:systemd/lifeos-energy-opportunity-attention.timer"; do
  src=${pair%%:*}; dst=${pair#*:}
  [[ -e "$src" ]] && cp -a "$src" "$BACKUP/$dst"
done
timer_enabled=$(systemctl is-enabled lifeos-energy-opportunity-attention.timer 2>/dev/null || true)
printf '%s\n' "$timer_enabled" >"$BACKUP/timer-enabled"

rollback() {
  rc=$?
  [[ $MUTATED -eq 1 ]] || exit "$rc"
  echo ENERGY_OPPORTUNITY_API_ROLLBACK=STARTED
  for pair in \
    "energy/app/main.py:$TARGET/app/main.py" \
    "energy/app/services/opportunities.py:$TARGET/app/services/opportunities.py" \
    "energy/app/routers/opportunities.py:$TARGET/app/routers/opportunities.py" \
    "ha/packages/lifeos_energy_attention.yaml:$HA_TARGET/packages/lifeos_energy_attention.yaml" \
    "ha/scripts/lifeos_energy_attention_sensor.py:$HA_TARGET/scripts/lifeos_energy_attention_sensor.py"; do
    src=${pair%%:*}; dst=${pair#*:}
    if [[ -e "$BACKUP/$src" ]]; then cp -a "$BACKUP/$src" "$dst"; else rm -f "$dst"; fi
  done
  for unit in lifeos-energy-opportunity-attention.service lifeos-energy-opportunity-attention.timer; do
    if [[ -e "$BACKUP/systemd/$unit" ]]; then
      cp -a "$BACKUP/systemd/$unit" "/etc/systemd/system/$unit"
    fi
  done
  systemctl daemon-reload || true
  [[ "$(cat "$BACKUP/timer-enabled")" == enabled ]] && \
    systemctl enable --now lifeos-energy-opportunity-attention.timer || true
  docker compose -f "$TARGET/docker-compose.yml" up -d --build lifeos-energy || true
  docker restart homeassistant >/dev/null 2>&1 || true
  echo ENERGY_OPPORTUNITY_API_ROLLBACK=COMPLETE
  exit "$rc"
}
trap rollback ERR

MUTATED=1
install -o joshan -g joshan -m 0644 "$SOURCE/app/main.py" "$TARGET/app/main.py"
install -o joshan -g joshan -m 0644 \
  "$SOURCE/app/services/opportunities.py" "$TARGET/app/services/opportunities.py"
install -o joshan -g joshan -m 0644 \
  "$SOURCE/app/routers/opportunities.py" "$TARGET/app/routers/opportunities.py"

docker compose -f "$TARGET/docker-compose.yml" up -d --build lifeos-energy
for _ in $(seq 1 90); do
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' lifeos-energy 2>/dev/null || true)
  [[ "$health" == healthy ]] && break
  sleep 2
done
[[ "${health:-}" == healthy ]] || fail "lifeos_energy_health:${health:-missing}"

python3 - <<'PY'
import json, urllib.request
for path in ('/health','/api/status','/api/energy/opportunities/current'):
    with urllib.request.urlopen('http://127.0.0.1:8110'+path,timeout=10) as response:
        assert response.status == 200
        payload=json.load(response)
        assert isinstance(payload,dict)
status=json.load(urllib.request.urlopen('http://127.0.0.1:8110/api/status',timeout=10))
assert status['modules']['energy_opportunities']=='ready'
opps=json.load(urllib.request.urlopen('http://127.0.0.1:8110/api/energy/opportunities/current',timeout=10))
assert opps['state'] in {'clear','attention','unavailable'}
assert isinstance(opps['opportunity_ids'],list)
print('ENERGY_OPPORTUNITY_API_LIVE=PASS')
PY

install -o joshan -g joshan -m 0644 \
  "$HA_SOURCE/packages/lifeos_energy_attention.yaml" \
  "$HA_TARGET/packages/lifeos_energy_attention.yaml"
install -o joshan -g joshan -m 0755 \
  "$HA_SOURCE/scripts/lifeos_energy_attention_sensor.py" \
  "$HA_TARGET/scripts/lifeos_energy_attention_sensor.py"
docker exec homeassistant python -m homeassistant --script check_config -c /config

systemctl disable --now lifeos-energy-opportunity-attention.timer 2>/dev/null || true
rm -f /etc/systemd/system/lifeos-energy-opportunity-attention.timer \
  /etc/systemd/system/lifeos-energy-opportunity-attention.service
systemctl daemon-reload
systemctl reset-failed lifeos-energy-opportunity-attention.service 2>/dev/null || true
rm -f "$HA_TARGET/lifeos_energy_opportunity_attention.json"

docker restart homeassistant >/dev/null
for _ in $(seq 1 90); do
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
  [[ "$health" == healthy || "$health" == running ]] && break
  sleep 2
done
[[ "$health" == healthy || "$health" == running ]] || fail "homeassistant_health:$health"

docker exec homeassistant python3 /config/scripts/lifeos_energy_attention_sensor.py | \
  python3 -c "import json,sys; d=json.load(sys.stdin); assert d['state'] in {'clear','attention','unavailable'}; assert isinstance(d['opportunity_ids'],list)"
[[ "$(systemctl is-enabled lifeos-energy-opportunity-attention.timer 2>/dev/null || true)" != enabled ]]
[[ ! -e /etc/systemd/system/lifeos-energy-opportunity-attention.timer ]]
[[ ! -e /etc/systemd/system/lifeos-energy-opportunity-attention.service ]]

trap - ERR
MUTATED=0
echo ENERGY_OPPORTUNITY_LEGACY_TIMER=RETIRED
echo ENERGY_OPPORTUNITY_JSON_BRIDGE=RETIRED
echo ENERGY_OPPORTUNITY_API_DEPLOY=PASS
echo "ROLLBACK_BACKUP=$BACKUP"
