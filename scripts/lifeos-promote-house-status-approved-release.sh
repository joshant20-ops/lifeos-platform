#!/usr/bin/env bash
set -Eeuo pipefail
PLATFORM=/home/joshan/lifeos-platform
HA=/opt/stacks/homeassistant/config
RELEASE=${1:-}; APP_SHA=${2:-}; ARTIFACT_DIR=${3:-}
MANIFEST="$PLATFORM/homeassistant/releases/house-status/live/approved-release.json"
GATE="$PLATFORM/homeassistant/verify-house-status-live-release.py"
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo HOUSE_STATUS_LIVE_RELEASE=FAIL:must_run_as_root; exit 1; }
[[ -n "$RELEASE" && -n "$APP_SHA" && -n "$ARTIFACT_DIR" ]] || { echo HOUSE_STATUS_LIVE_RELEASE=FAIL:explicit_release_identity_required; exit 1; }
[[ "$RELEASE" =~ ^v[3-9][0-9]+$ ]] || { echo HOUSE_STATUS_LIVE_RELEASE=FAIL:release_must_be_v30_or_later; exit 1; }
python3 "$GATE" --request-release "$RELEASE" --request-sha256 "$APP_SHA" --verify-dev-evidence
APP="$ARTIFACT_DIR/lifeos-house-status-$RELEASE.js"; BELL="$ARTIFACT_DIR/lifeos-house-status-doorbell-$RELEASE.js"
[[ -s "$APP" && -s "$BELL" ]] || { echo HOUSE_STATUS_LIVE_RELEASE=FAIL:generated_assets_missing; exit 1; }
EXPECTED_BELL=$(python3 - "$MANIFEST" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['promotion_candidate']['doorbell_sha256'])
PY
)
[[ "$(sha256sum "$APP" | cut -d' ' -f1)" == "$APP_SHA" ]] || { echo HOUSE_STATUS_LIVE_RELEASE=FAIL:app_hash_mismatch; exit 1; }
[[ "$(sha256sum "$BELL" | cut -d' ' -f1)" == "$EXPECTED_BELL" ]] || { echo HOUSE_STATUS_LIVE_RELEASE=FAIL:doorbell_hash_mismatch; exit 1; }
ASSETS="$HA/www/house-status"; CONFIG="$HA/configuration.yaml"; STAMP=$(date -u +%Y%m%dT%H%M%SZ); BACKUP="$HA/.storage/house-status-release-$STAMP"
APP_TARGET="$ASSETS/lifeos-house-status-$RELEASE.js"; BELL_TARGET="$ASSETS/lifeos-house-status-doorbell-$RELEASE.js"
mkdir -p "$BACKUP" "$ASSETS"; cp -a "$CONFIG" "$BACKUP/configuration.yaml"
[[ -f "$APP_TARGET" ]] && cp -a "$APP_TARGET" "$BACKUP/app.js" || true
[[ -f "$BELL_TARGET" ]] && cp -a "$BELL_TARGET" "$BACKUP/doorbell.js" || true
MUTATED=0
rollback(){ rc=$?; if [[ "$MUTATED" -eq 1 && "$rc" -ne 0 ]]; then cp -a "$BACKUP/configuration.yaml" "$CONFIG"; [[ -f "$BACKUP/app.js" ]] && cp -a "$BACKUP/app.js" "$APP_TARGET" || rm -f "$APP_TARGET"; [[ -f "$BACKUP/doorbell.js" ]] && cp -a "$BACKUP/doorbell.js" "$BELL_TARGET" || rm -f "$BELL_TARGET"; docker restart homeassistant >/dev/null || true; echo HOUSE_STATUS_LIVE_ROLLBACK=COMPLETE; fi; exit "$rc"; }
trap rollback EXIT
MUTATED=1
install -o root -g root -m 0644 "$APP" "$APP_TARGET"; install -o root -g root -m 0644 "$BELL" "$BELL_TARGET"
python3 - "$CONFIG" "$RELEASE" "$EXPECTED_BELL" <<'PY'
from pathlib import Path
import re,sys
p=Path(sys.argv[1]); release=sys.argv[2]; bell_hash=sys.argv[3]; lines=p.read_text().splitlines(True); out=[]; i=0
name=re.compile(r'^  - name: lifeos-house-status(?:-v\d+)?\s*$')
while i<len(lines):
    if name.match(lines[i].rstrip('\n')):
        i+=1
        while i<len(lines) and not lines[i].startswith('  - name:') and not (lines[i] and not lines[i][0].isspace()): i+=1
        continue
    out.append(lines[i]); i+=1
panel=(f'  - name: lifeos-house-status-{release}\n' '    sidebar_title: House Status\n' '    sidebar_icon: mdi:home-heart\n' '    url_path: house-status\n' f'    module_url: /local/house-status/lifeos-house-status-{release}.js?v={bell_hash[:12]}\n' '    require_admin: false\n' '    config:\n' '      mode: domestic\n')
text=''.join(out); match=re.search(r'(?m)^panel_custom:\s*\n',text)
if not match: raise SystemExit('HOUSE_STATUS_LIVE_CONFIG=FAIL:panel_custom_missing')
p.write_text(text[:match.end()]+panel+text[match.end():])
PY
docker exec homeassistant python -m homeassistant --script check_config -c /config >/dev/null
docker restart homeassistant >/dev/null
for _ in $(seq 1 60); do state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true); [[ "$state" == healthy || "$state" == running ]] && break; sleep 2; done
state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' homeassistant 2>/dev/null || true)
[[ "$state" == healthy || "$state" == running ]] || { echo HOUSE_STATUS_LIVE_RELEASE=FAIL:homeassistant_not_healthy; exit 1; }
python3 - "$CONFIG" "$RELEASE" "$APP_TARGET" "$APP_SHA" <<'PY'
from pathlib import Path
import hashlib,sys
cfg=Path(sys.argv[1]).read_text(); release=sys.argv[2]; asset=Path(sys.argv[3]); expected=sys.argv[4]
if f'name: lifeos-house-status-{release}' not in cfg or f'/local/house-status/lifeos-house-status-{release}.js' not in cfg: raise SystemExit('HOUSE_STATUS_LIVE_CONFIG=FAIL:registration_mismatch')
if hashlib.sha256(asset.read_bytes()).hexdigest()!=expected: raise SystemExit('HOUSE_STATUS_LIVE_ASSET=FAIL:installed_hash_mismatch')
PY
MUTATED=0; trap - EXIT
echo HOUSE_STATUS_LIVE_RELEASE=$RELEASE
echo HOUSE_STATUS_LIVE_ARTIFACT_SHA256=$APP_SHA
echo HOUSE_STATUS_LIVE_DEPLOY=PASS
