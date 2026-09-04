#!/usr/bin/env bash
set -Eeuo pipefail

readonly CONTROL=/home/joshan/lifeos-pi-control
readonly PLATFORM=/home/joshan/lifeos-platform
readonly HISTORICAL_CONTROL_COMMIT=29bf111d4021fe9eb9f5e6c0e409c039167b1fdd
readonly STALE_ID=activate-engineer-v1-660a6d4862fa
readonly STALE_MANIFEST="jobs/pending/${STALE_ID}.json"
readonly STALE_SCRIPT="jobs/root-scripts/${STALE_ID}.sh"
readonly STALE_SCRIPT_SHA=bd24600e7abfda6e18bbd725fe0f9814a575795e8748b38951c2bb6eb85c6878
readonly MIGRATION_REL=scripts/migrate-lifeos-control-runtime-ownership.sh
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly EVIDENCE_DIR="/home/joshan/lifeos-control-runtime-backups/${STAMP}-historical-stale-evidence"
readonly MIGRATION_TMP=/tmp/lifeos-control-runtime-ownership-migration.sh

SUBMIT_SOCKET_WAS_ACTIVE=0
ACTIVE_UNITS=()
WRITERS_STOPPED=0
REHYDRATED=0

fail(){
  echo 'WRAPPER_STATUS=FAIL'
  echo "FAIL_REASON=$*"
  echo "EVIDENCE_DIR=$EVIDENCE_DIR"
  exit 1
}

restore_writers(){
  set +e
  local u
  for u in "${ACTIVE_UNITS[@]}"; do sudo systemctl start "$u" >/dev/null 2>&1 || true; done
  (( SUBMIT_SOCKET_WAS_ACTIVE )) && sudo systemctl start lifeos-control-job-submit.socket >/dev/null 2>&1 || true
}

on_exit(){
  local rc=$?
  if (( rc != 0 && WRITERS_STOPPED )); then
    echo 'CONTROL_WRITERS_LEFT_STOPPED=YES'
    echo 'CONTROL_WRITERS_STOP_REASON=historical-evidence wrapper or migration failed after quiesce'
  fi
  exit "$rc"
}
trap on_exit EXIT

sha(){ sha256sum "$1" | awk '{print $1}'; }

[[ "$(id -un)" == joshan ]] || fail 'must run as joshan'
for c in git python3 sha256sum sudo systemctl flock; do command -v "$c" >/dev/null || fail "missing command: $c"; done
sudo -v || fail 'sudo authentication failed'
[[ -d "$CONTROL/.git" && -d "$PLATFORM/.git" ]] || fail 'required repository missing'
[[ "$(git -C "$CONTROL" branch --show-current)" == main ]] || fail 'control repo must be on main'
[[ "$(git -C "$PLATFORM" branch --show-current)" == main ]] || fail 'platform repo must be on main'
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 'control tracked tree is dirty'
[[ -z "$(git -C "$PLATFORM" status --porcelain --untracked-files=no)" ]] || fail 'platform tracked tree is dirty'
mkdir -p "$EVIDENCE_DIR"

git -C "$CONTROL" cat-file -e "${HISTORICAL_CONTROL_COMMIT}^{commit}" || fail 'historical control commit unavailable'
git -C "$CONTROL" merge-base --is-ancestor "$HISTORICAL_CONTROL_COMMIT" HEAD || fail 'historical activation commit is not in local control ancestry'

manifest="$CONTROL/$STALE_MANIFEST"
script="$CONTROL/$STALE_SCRIPT"
result="$CONTROL/results/${STALE_ID}.json"
archive="$CONTROL/jobs/archive/${STALE_ID}.json"
qdir="$CONTROL/state/quarantined-jobs"

if [[ -e "$manifest" || -e "$script" || -e "$result" || -e "$archive" ]]; then
  fail 'live stale activation state changed; wrapper requires manifest/script/result/archive all absent'
fi
if [[ -d "$qdir" ]] && find "$qdir" -maxdepth 1 -type f -name "${STALE_ID}.*" -print -quit | grep -q .; then
  fail 'stale activation is already quarantined; do not rehydrate again'
fi

git -C "$CONTROL" show "$HISTORICAL_CONTROL_COMMIT:$STALE_MANIFEST" > "$EVIDENCE_DIR/historical-manifest.json" || fail 'cannot extract historical manifest'
git -C "$CONTROL" show "$HISTORICAL_CONTROL_COMMIT:$STALE_SCRIPT" > "$EVIDENCE_DIR/historical-script.sh" || fail 'cannot extract historical script'
[[ "$(sha "$EVIDENCE_DIR/historical-script.sh")" == "$STALE_SCRIPT_SHA" ]] || fail 'historical script checksum mismatch'
python3 - "$EVIDENCE_DIR/historical-manifest.json" "$STALE_SCRIPT" "$STALE_SCRIPT_SHA" <<'PY' || fail 'historical manifest validation failed'
import json,sys
p,rel,want=sys.argv[1:]
d=json.load(open(p))
assert d['schema_version']==1
assert d['job_id']=='activate-engineer-v1-660a6d4862fa'
assert d['target']=='pi5'
assert d['job_type']=='change'
assert d['change_scope']=='root-broker'
assert d['change_policy']=='gated-v1'
assert d['requires_root'] is True
assert d['script']==rel
assert d['script_sha256']==want
PY
sha256sum "$EVIDENCE_DIR/historical-manifest.json" "$EVIDENCE_DIR/historical-script.sh" > "$EVIDENCE_DIR/historical.sha256"
echo "HISTORICAL_EVIDENCE=PASS commit=$HISTORICAL_CONTROL_COMMIT"

if systemctl is-active --quiet lifeos-control-job-submit.socket; then
  SUBMIT_SOCKET_WAS_ACTIVE=1
  sudo systemctl stop lifeos-control-job-submit.socket || fail 'cannot stop submission socket'
fi
while IFS= read -r u; do
  [[ -n "$u" ]] || continue
  if systemctl cat "$u" 2>/dev/null | grep -Eq 'lifeos-job-publisher|lifeos-pi-control-runner'; then
    systemctl is-active --quiet "$u" && ACTIVE_UNITS+=("$u") || true
  fi
done < <(systemctl list-unit-files --type=service --type=timer --no-legend 2>/dev/null | awk '{print $1}')
for u in "${ACTIVE_UNITS[@]}"; do sudo systemctl stop "$u" || fail "cannot stop $u"; done
WRITERS_STOPPED=1

mkdir -p "$CONTROL/state" /home/joshan/.local/state/lifeos-pi-control
exec 8>"$CONTROL/state/publisher.lock"; flock -n 8 || fail 'publisher lock still held'
exec 9>/home/joshan/.local/state/lifeos-pi-control/runner.lock; flock -n 9 || fail 'runner lock still held'
pgrep -af 'lifeos-(job-publisher|pi-control-runner)' >/dev/null && fail 'control writer process remains active' || true
echo 'CONTROL_WRITERS=QUIESCED'

mkdir -p "$(dirname "$manifest")" "$(dirname "$script")"
install -m 0640 "$EVIDENCE_DIR/historical-manifest.json" "$manifest" || fail 'cannot rehydrate stale manifest'
install -m 0750 "$EVIDENCE_DIR/historical-script.sh" "$script" || fail 'cannot rehydrate stale script'
[[ "$(sha "$script")" == "$STALE_SCRIPT_SHA" ]] || fail 'rehydrated script checksum mismatch'
cmp -s "$manifest" "$EVIDENCE_DIR/historical-manifest.json" || fail 'rehydrated manifest differs from historical evidence'
REHYDRATED=1
echo 'STALE_ACTIVATION_REHYDRATED=PASS writers=stopped'

# Release the wrapper locks before invoking the migration. Writers remain stopped,
# so the migration can acquire its own locks without any execution race.
flock -u 8
flock -u 9
exec 8>&-
exec 9>&-

git -C "$PLATFORM" show "HEAD:$MIGRATION_REL" > "$MIGRATION_TMP" || fail 'cannot extract canonical migration script'
chmod 700 "$MIGRATION_TMP"
bash -n "$MIGRATION_TMP" || fail 'canonical migration syntax failed'

echo 'MIGRATION_CHAIN=START'
set +e
"$MIGRATION_TMP"
MIGRATION_RC=$?
set -e
echo "MIGRATION_CHAIN_RC=$MIGRATION_RC"

if (( MIGRATION_RC != 0 )); then
  fail "canonical migration failed rc=$MIGRATION_RC"
fi

[[ ! -f "$manifest" ]] || fail 'stale manifest still pending after successful migration'
find "$CONTROL/state/quarantined-jobs" -maxdepth 1 -type f -name "${STALE_ID}.*.json" -print -quit | grep -q . || fail 'quarantined stale activation evidence missing after migration'

restore_writers
WRITERS_STOPPED=0
ACTIVE_UNITS=()
SUBMIT_SOCKET_WAS_ACTIVE=0
trap - EXIT

echo 'WRAPPER_STATUS=PASS'
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
echo 'NEXT_REQUIRED=fresh_engineer_activation_from_live_evidence'
