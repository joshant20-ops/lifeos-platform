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
BACKUP_DIR=
HA_CHANGED=false
HA_RESTARTED=false
HA_CONTAINER=
ROLLING_BACK=false
FAILURE_ACTIVE=false

rollback_ha() {
  [[ "$HA_CHANGED" == true && -n "$BACKUP_DIR" ]] || return 0
  [[ "$ROLLING_BACK" == false ]] || { printf 'HA_ROLLBACK=FAIL reason=recursive_attempt\n' >&2; return 1; }
  ROLLING_BACK=true
  printf 'HA_ROLLBACK=START backup=%s\n' "$BACKUP_DIR"
  cp -a "$BACKUP_DIR/configuration.yaml" "$HA_CONFIG" || {
    printf 'HA_ROLLBACK=FAIL reason=configuration_restore_failed\n' >&2
    return 1
  }
  if [[ -f "$BACKUP_DIR/lifeos_assistant_panel.yaml" ]]; then
    cp -a "$BACKUP_DIR/lifeos_assistant_panel.yaml" "$HA_PANEL" || {
      printf 'HA_ROLLBACK=FAIL reason=panel_restore_failed\n' >&2
      return 1
    }
  else
    rm -f "$HA_PANEL" || {
      printf 'HA_ROLLBACK=FAIL reason=panel_remove_failed\n' >&2
      return 1
    }
  fi
  # If HA already loaded the candidate configuration, restoring files alone is
  # insufficient: restart it once more so the last-known-good config is active.
  if [[ "$HA_RESTARTED" == true && -n "$HA_CONTAINER" ]]; then
    printf 'HA_ROLLBACK_RESTART=START\n'
    timeout 120 docker restart "$HA_CONTAINER" >/dev/null || {
      printf 'HA_ROLLBACK=FAIL reason=restored_config_restart_failed\n' >&2
      return 1
    }
    wait_url http://127.0.0.1:8123/ 180 || {
      printf 'HA_ROLLBACK=FAIL reason=restored_config_startup_timeout\n' >&2
      return 1
    }
    printf 'HA_ROLLBACK_RESTART=PASS\n'
  fi
  printf 'HA_ROLLBACK=PASS\n'
  HA_CHANGED=false
  HA_RESTARTED=false
  ROLLING_BACK=false
}

fail() {
  local reason=${1:-unknown_failure}
  if [[ "$FAILURE_ACTIVE" == true ]]; then
    printf 'RESULT=FAIL job=%s reason=recursive_failure original=%s\n' "$JOB_ID" "$reason" >&2
    exit 1
  fi
  FAILURE_ACTIVE=true
  # Recovery and diagnostics must never re-enter this handler through ERR.
  trap - ERR
  rollback_ha || true
  printf 'RESULT=FAIL job=%s reason=%s\n' "$JOB_ID" "$reason"
  docker ps -a --filter 'name=^/lifeos-engineer-ui$' --no-trunc || true
  docker inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} exit={{.State.ExitCode}} error={{.State.Error}}' lifeos-engineer-ui || true
  docker logs --tail 200 --timestamps lifeos-engineer-ui || true
  systemctl --no-pager --full status lifeos-engineer.service || true
  journalctl -u lifeos-engineer.service -n 200 --no-pager || true
  printf '\n===== ENDPOINT DIAGNOSTICS =====\n'
  curl -sS -i --max-time 10 "$BACKEND_HEALTH" || true
  curl -sS -i --max-time 10 "$UI_HEALTH" || true
  if [[ -n "$HA_CONTAINER" ]]; then
    printf '\n===== HOME ASSISTANT DIAGNOSTICS =====\n'
    docker ps -a --filter "name=^/${HA_CONTAINER}$" --no-trunc || true
    docker inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} exit={{.State.ExitCode}} error={{.State.Error}}' "$HA_CONTAINER" || true
    docker logs --tail 200 --timestamps "$HA_CONTAINER" || true
    docker exec "$HA_CONTAINER" python3 -m homeassistant --script check_config -c /config || true
  fi
  exit 1
}
trap 'fail unexpected_error_at_line_$LINENO' ERR

wait_url() {
  local url=$1 limit=$2 delay=1 started
  started=$(date +%s)
  until curl -fsS --max-time 5 "$url" >/dev/null 2>&1; do
    (( $(date +%s) - started < limit )) || return 1
    sleep "$delay"
    if (( delay < 16 )); then
      delay=$((delay * 2))
    fi
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
printf 'HA_CONTAINER=%s\n' "$HA_CONTAINER"
# Do not confuse a still-starting Home Assistant with a broken integration.
# Its compose healthcheck also uses this endpoint, but waiting here provides a
# deterministic budget and useful failure diagnostics for direct invocations.
wait_url http://127.0.0.1:8123/ 180 || fail home_assistant_not_ready
timeout 30 docker exec "$HA_CONTAINER" python3 - "http://${LAN_IP}:8792/health" <<'PY' || fail home_assistant_cannot_reach_engineer
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
  HA_CHANGED=true
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
  HA_CHANGED=true
  timeout 180 docker exec "$HA_CONTAINER" python3 -m homeassistant --script check_config -c /config >/dev/null || fail home_assistant_config_invalid
  # Mark the restart attempt before invoking Docker. Even an interrupted or
  # timed-out restart may have loaded the candidate files and needs recovery.
  HA_RESTARTED=true
  timeout 120 docker restart "$HA_CONTAINER" >/dev/null || fail home_assistant_restart_failed
  wait_url http://127.0.0.1:8123/ 180 || fail home_assistant_startup_timeout
  printf 'HA_PANEL=UPDATED old_engineering_prototype_replaced\n'
fi
timeout 180 docker exec "$HA_CONTAINER" python3 -m homeassistant --script check_config -c /config >/dev/null || fail home_assistant_config_invalid
grep -q '^lifeos_engineer:$' "$HA_PANEL" || fail home_assistant_engineer_panel_missing
grep -q "url: http://${LAN_IP}:8792/" "$HA_PANEL" || fail home_assistant_engineer_url_wrong
# panel_iframe routes are served by the HA frontend. Follow authentication
# redirects and accept the normal unauthenticated outcomes; a 404 proves that
# the configured sidebar route was not registered.
HA_ROUTE_CODE=$(curl -sS -L -o /dev/null -w '%{http_code}' --max-time 15 \
  http://127.0.0.1:8123/lifeos_engineer) || fail home_assistant_engineer_route_unreachable
[[ "$HA_ROUTE_CODE" == 200 || "$HA_ROUTE_CODE" == 401 ]] || fail "home_assistant_engineer_route_status_${HA_ROUTE_CODE}"
printf 'HA_CONFIG_CHECK=PASS\n'
printf 'HA_PANEL_ROUTE=PASS status=%s\n' "$HA_ROUTE_CODE"
printf 'HA_NAVIGATION=Home_Assistant_sidebar_>_LifeOS_Engineer\n'
printf 'HA_BACKUP=%s\n' "$BACKUP_DIR"
HA_CHANGED=false
HA_RESTARTED=false

printf 'RESULT=PASS job=%s\n' "$JOB_ID"
printf 'CHECKS=backend_/health,openwebui_/health,home_assistant_reachability\n'
