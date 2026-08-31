#!/usr/bin/env bash
set -euo pipefail

JOB_ID=ebf8a71d4bff
REPO=/home/joshan/lifeos-platform
DEPLOY="$REPO/governor/scripts/deploy-engineer-ai.sh"
UI_HEALTH=http://127.0.0.1:8792/health
BACKEND_HEALTH=http://127.0.0.1:8793/health
TIMEOUT_SECONDS=900
HA_CONFIG_DIR=/opt/stacks/homeassistant/config
HA_CONFIG="$HA_CONFIG_DIR/configuration.yaml"
HA_PANEL="$HA_CONFIG_DIR/lifeos_assistant_panel.yaml"

fail() {
  printf 'RESULT=FAIL job=%s reason=%s\n' "$JOB_ID" "$1"
  docker ps -a --filter 'name=^/lifeos-engineer-ui$' --no-trunc || true
  docker inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} exit={{.State.ExitCode}} error={{.State.Error}}' lifeos-engineer-ui || true
  docker logs --tail 200 --timestamps lifeos-engineer-ui || true
  systemctl --no-pager --full status lifeos-engineer.service || true
  journalctl -u lifeos-engineer.service -n 200 --no-pager || true
  exit 1
}
trap 'fail unexpected_error_at_line_$LINENO' ERR

wait_url() {
  local url=$1 limit=$2 delay=1 started
  started=$(date +%s)
  until curl -fsS --max-time 5 "$url" >/dev/null 2>&1; do
    (( $(date +%s) - started < limit )) || return 1
    sleep "$delay"
    (( delay < 16 )) && delay=$((delay * 2))
  done
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ -x "$DEPLOY" ]] || fail deploy_script_missing

timeout "$TIMEOUT_SECONDS" "$DEPLOY" || fail deployment_failed

BACKEND_JSON=$(curl -fsS --max-time 10 "$BACKEND_HEALTH") || fail backend_health_failed
UI_JSON=$(curl -fsS --max-time 10 "$UI_HEALTH") || fail ui_health_failed
python3 - "$BACKEND_JSON" <<'PY' || fail backend_health_invalid
import json, sys
data = json.loads(sys.argv[1])
assert data["status"] == "ok", data
print("BACKEND_HEALTH=PASS")
PY
python3 - "$UI_JSON" <<'PY' || fail ui_health_invalid
import json, sys
data = json.loads(sys.argv[1])
assert data.get("status") is True or data.get("status") == "ok", data
print("OPEN_WEBUI_HEALTH=PASS")
PY

# Home Assistant must be able to reach the same LAN endpoint used by its iframe.
LAN_IP=$(hostname -I | awk '{print $1}')
HA_CONTAINER=$(docker ps --format '{{.Names}}' | awk '/^(homeassistant|home-assistant)$/ {print; exit}')
if [[ -z "$HA_CONTAINER" ]]; then
  fail home_assistant_container_not_running
fi
docker exec "$HA_CONTAINER" python3 - "http://${LAN_IP}:8792/health" <<'PY' || fail home_assistant_cannot_reach_engineer
import json, sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=10) as response:
    data = json.load(response)
assert data.get("status") is True or data.get("status") == "ok", data
print("HOME_ASSISTANT_TO_ENGINEER=PASS")
PY

# Finish the earlier supported panel_iframe integration without touching
# storage-mode dashboards. Preserve the existing include filename so upgrades
# are idempotent, but replace the old engineering prototype panel itself.
[[ -f "$HA_CONFIG" ]] || fail home_assistant_configuration_missing
BACKUP_DIR="$HA_CONFIG_DIR/.lifeos-backups/engineer-panel-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
cp -a "$HA_CONFIG" "$BACKUP_DIR/configuration.yaml"
[[ ! -f "$HA_PANEL" ]] || cp -a "$HA_PANEL" "$BACKUP_DIR/lifeos_assistant_panel.yaml"
PANEL_ROOTS=$(grep -Ec '^panel_iframe:' "$HA_CONFIG" || true)
if [[ "$PANEL_ROOTS" -eq 0 ]]; then
  printf '\npanel_iframe: !include lifeos_assistant_panel.yaml\n' >>"$HA_CONFIG"
elif [[ "$PANEL_ROOTS" -ne 1 ]] || ! grep -Eq '^panel_iframe:[[:space:]]*!include[[:space:]]+lifeos_assistant_panel\.yaml[[:space:]]*$' "$HA_CONFIG"; then
  fail unsupported_existing_panel_iframe_configuration
fi

PANEL_TMP=$(mktemp "$HA_CONFIG_DIR/.lifeos-engineer-panel.XXXXXX")
cat >"$PANEL_TMP" <<YAML
lifeos_engineer:
  title: LifeOS Engineer
  icon: mdi:tools
  url: http://${LAN_IP}:8792/
  require_admin: false
YAML
if [[ -f "$HA_PANEL" ]] && cmp -s "$PANEL_TMP" "$HA_PANEL"; then
  rm -f "$PANEL_TMP"
  printf 'HA_PANEL=PASS already_current\n'
else
  install -m 0644 "$PANEL_TMP" "$HA_PANEL"
  rm -f "$PANEL_TMP"
  timeout 180 docker exec "$HA_CONTAINER" python3 -m homeassistant --script check_config -c /config >/dev/null || fail home_assistant_config_invalid
  timeout 120 docker restart "$HA_CONTAINER" >/dev/null || fail home_assistant_restart_failed
  wait_url http://127.0.0.1:8123/ 180 || fail home_assistant_startup_timeout
  printf 'HA_PANEL=UPDATED old_engineering_prototype_replaced\n'
fi
timeout 180 docker exec "$HA_CONTAINER" python3 -m homeassistant --script check_config -c /config >/dev/null || fail home_assistant_config_invalid
grep -q '^lifeos_engineer:$' "$HA_PANEL" || fail home_assistant_engineer_panel_missing
grep -q "url: http://${LAN_IP}:8792/" "$HA_PANEL" || fail home_assistant_engineer_url_wrong
printf 'HA_CONFIG_CHECK=PASS\n'
printf 'HA_NAVIGATION=Home_Assistant_sidebar_>_LifeOS_Engineer\n'
printf 'HA_BACKUP=%s\n' "$BACKUP_DIR"

printf 'RESULT=PASS job=%s\n' "$JOB_ID"
printf 'CHECKS=backend_/health,openwebui_/health,home_assistant_reachability\n'
