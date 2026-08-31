#!/usr/bin/env bash
set -Eeuo pipefail

readonly HA_CONFIG_DIR="/opt/stacks/homeassistant/config"
readonly HA_CONFIG="${HA_CONFIG_DIR}/configuration.yaml"
readonly PANEL_CONFIG="${HA_CONFIG_DIR}/lifeos_assistant_panel.yaml"
readonly HA_CONTAINER="homeassistant"
readonly ASSISTANT_URL="http://192.168.0.203:8791/"
readonly HA_URL="http://127.0.0.1:8123"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly RUN_ID
readonly BACKUP_DIR="${HA_CONFIG_DIR}/.lifeos-backups/assistant-panel-${RUN_ID}"
CHANGED=0

fail() {
  printf 'FAIL=%s\n' "$1" >&2
  printf 'RESULT=FAIL\n' >&2
  exit 1
}

command -v timeout >/dev/null || fail "timeout_command_missing"
command -v curl >/dev/null || fail "curl_command_missing"
command -v docker >/dev/null || fail "docker_command_missing"
[[ -f "$HA_CONFIG" ]] || fail "home_assistant_configuration_missing"
docker inspect "$HA_CONTAINER" >/dev/null 2>&1 || fail "home_assistant_container_missing"

printf 'TARGET=Home Assistant sidebar / LifeOS AI\n'
printf 'ASSISTANT_URL=%s\n' "$ASSISTANT_URL"

# Check the real conversational page before touching Home Assistant.  This uses
# only stable labels and never prints conversation or Home Assistant data.
assistant_html="$(timeout 10s curl --fail --silent --show-error \
  --connect-timeout 3 --max-time 8 "$ASSISTANT_URL")" \
  || fail "assistant_ui_unreachable_from_pi5"
grep -Fq '<title>LifeOS Assistant</title>' <<<"$assistant_html" \
  || fail "assistant_conversation_ui_marker_missing"
grep -Fq 'Run this' <<<"$assistant_html" \
  || fail "assistant_approval_control_missing"
printf 'ASSISTANT_UI_FROM_PI5=PASS\n'

# A host-networked HA container should be able to fetch the exact iframe URL.
# Verify that point of view explicitly, without exposing the returned page.
timeout 15s docker exec "$HA_CONTAINER" python3 - "$ASSISTANT_URL" <<'PY' \
  || fail "assistant_ui_unreachable_from_home_assistant"
import sys
import urllib.request

request = urllib.request.Request(sys.argv[1], headers={"User-Agent": "HomeAssistant-LifeOS-check"})
with urllib.request.urlopen(request, timeout=8) as response:
    body = response.read(512_000).decode("utf-8", "replace")
    assert response.status == 200
    assert "<title>LifeOS Assistant</title>" in body
    assert "Run this" in body
print("ASSISTANT_UI_FROM_HA_CONTAINER=PASS")
PY

mkdir -p "$BACKUP_DIR"
cp -a "$HA_CONFIG" "$BACKUP_DIR/configuration.yaml"
[[ ! -e "$PANEL_CONFIG" ]] || cp -a "$PANEL_CONFIG" "$BACKUP_DIR/lifeos_assistant_panel.yaml"

rollback() {
  [[ "$CHANGED" -eq 1 ]] || return 0
  cp -a "$BACKUP_DIR/configuration.yaml" "$HA_CONFIG"
  if [[ -f "$BACKUP_DIR/lifeos_assistant_panel.yaml" ]]; then
    cp -a "$BACKUP_DIR/lifeos_assistant_panel.yaml" "$PANEL_CONFIG"
  else
    rm -f "$PANEL_CONFIG"
  fi
  timeout 120s docker restart "$HA_CONTAINER" >/dev/null 2>&1 || true
}

# Never edit storage-mode Lovelace internals. panel_iframe is a supported YAML
# integration and creates one native sidebar destination while leaving every
# existing dashboard and card untouched.
panel_root_count="$(sed -nE '/^panel_iframe:/p' "$HA_CONFIG" | wc -l)"
if [[ "$panel_root_count" -gt 1 ]]; then
  fail "multiple_existing_panel_iframe_roots_require_manual_reconciliation"
elif [[ "$panel_root_count" -eq 1 ]]; then
  if ! grep -Eq '^panel_iframe:[[:space:]]*!include[[:space:]]+lifeos_assistant_panel\.yaml[[:space:]]*$' "$HA_CONFIG"; then
    fail "existing_panel_iframe_configuration_not_owned_by_this_job"
  fi
else
  printf '\npanel_iframe: !include lifeos_assistant_panel.yaml\n' >>"$HA_CONFIG"
  CHANGED=1
fi

cat >"${PANEL_CONFIG}.new" <<'YAML'
lifeos_assistant:
  title: LifeOS AI
  icon: mdi:robot-outline
  url: http://192.168.0.203:8791/
  require_admin: false
YAML
if [[ ! -f "$PANEL_CONFIG" ]] || ! cmp -s "${PANEL_CONFIG}.new" "$PANEL_CONFIG"; then
  mv "${PANEL_CONFIG}.new" "$PANEL_CONFIG"
  CHANGED=1
else
  rm -f "${PANEL_CONFIG}.new"
fi

[[ "$(grep -Ec '^lifeos_assistant:$' "$PANEL_CONFIG")" -eq 1 ]] \
  || { rollback; fail "duplicate_lifeos_sidebar_entries"; }
[[ "$(grep -Ec '^panel_iframe:' "$HA_CONFIG")" -eq 1 ]] \
  || { rollback; fail "duplicate_panel_iframe_roots"; }

if ! timeout 180s docker exec "$HA_CONTAINER" python3 -m homeassistant \
  --script check_config -c /config >/dev/null; then
  rollback
  fail "home_assistant_config_validation_failed_and_rolled_back"
fi
printf 'HA_CONFIG_CHECK=PASS\n'

if [[ "$CHANGED" -eq 1 ]]; then
  if ! timeout 120s docker restart "$HA_CONTAINER" >/dev/null; then
    rollback
    fail "home_assistant_restart_failed_and_rolled_back"
  fi
fi

for _ in $(seq 1 30); do
  if timeout 5s curl --fail --silent --output /dev/null "$HA_URL/"; then
    break
  fi
  sleep 2
done
timeout 5s curl --fail --silent --output /dev/null "$HA_URL/" \
  || { rollback; fail "home_assistant_unhealthy_after_change_and_rolled_back"; }
printf 'HA_FRONTEND=PASS\n'

# HA serves client-side panel routes through its frontend shell. Authentication
# may redirect, so follow redirects and require the final response to load.
route_code="$(timeout 10s curl --silent --location --output /dev/null \
  --write-out '%{http_code}' --max-time 8 "$HA_URL/lifeos_assistant")" \
  || { rollback; fail "home_assistant_panel_route_unreachable"; }
[[ "$route_code" =~ ^(200|401)$ ]] \
  || { rollback; fail "unexpected_home_assistant_panel_route_status_${route_code}"; }
printf 'HA_PANEL_ROUTE=PASS status=%s\n' "$route_code"

# Exercise the explicit approved-job path with a harmless, read-only engineering
# brief. A queued job ID is evidence of submission; no private HA data is sent.
job_response="$(timeout 20s curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data '{"request":"Approved verification job: perform a read-only health check of the LifeOS Assistant service and report status. Make no configuration changes, do not access private data, and do not submit another job."}' \
  "${ASSISTANT_URL}run")" || fail "approved_job_submission_failed"
python3 - "$job_response" <<'PY' || fail "approved_job_response_invalid"
import json
import sys

result = json.loads(sys.argv[1])
assert isinstance(result.get("id"), str) and result["id"]
assert result.get("status") in {"QUEUED", "RUNNING", "PASS"}
print("APPROVED_ENGINEERING_JOB=PASS")
print("VERIFICATION_JOB_ID=" + result["id"])
PY

printf 'DUPLICATE_CHECK=PASS\n'
printf 'PUBLIC_EXPOSURE_CHANGE=NONE private_RFC1918_URL_only\n'
printf 'BACKUP=%s\n' "$BACKUP_DIR"
printf 'NAVIGATION=Home Assistant sidebar > LifeOS AI\n'
printf 'RESULT=PASS\n'
