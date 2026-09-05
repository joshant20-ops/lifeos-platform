#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM=/home/joshan/lifeos-platform
SOURCE="$PLATFORM/governor/job_records.py"
LIVE=/usr/local/libexec/job_records.py
SERVICE=lifeos-autonomous-agent.service
AUDIT_DIR=/var/lib/lifeos-control/step11
AUDIT="$AUDIT_DIR/step11-live-closure.json"
BACKUP="$AUDIT_DIR/job_records.py.pre-step11"
HAD_LIVE=0

fail() {
  echo "STEP_11=FAIL"
  echo "FAIL_REASON=$1"
  exit 1
}

rollback() {
  local rc=$?
  trap - ERR
  echo "ROLLBACK=START"
  if [[ "$HAD_LIVE" -eq 1 && -f "$BACKUP" ]]; then
    install -o root -g root -m 0644 "$BACKUP" "$LIVE" || true
  elif [[ "$HAD_LIVE" -eq 0 ]]; then
    rm -f "$LIVE" || true
  fi
  systemctl restart "$SERVICE" >/dev/null 2>&1 || true
  echo "ROLLBACK=DONE"
  echo "STEP_11=FAIL"
  echo "FAIL_REASON=live_closure_error"
  exit "$rc"
}
trap rollback ERR

[[ $(id -u) -eq 0 ]] || fail must_run_as_root
[[ -d "$PLATFORM/.git" ]] || fail platform_repo_missing
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail canonical_helper_missing_or_symlink

HEAD=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
ORIGIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
[[ "$HEAD" == "$ORIGIN" ]] || fail platform_not_at_origin_main
[[ -z "$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain)" ]] || fail platform_dirty
runuser -u joshan -- git -C "$PLATFORM" ls-files --error-unmatch -- governor/job_records.py >/dev/null

SOURCE_UID=$(stat -c '%u' "$SOURCE")
[[ "$SOURCE_UID" -eq 1000 ]] || fail canonical_helper_owner_unexpected

# Verify canonical bytes against the exact Git commit before repairing checkout
# metadata. Git does not track group/other write bits, so a checkout may carry
# unsafe mode bits even while its bytes are canonical. Only chmod this one
# verified tracked helper, then revalidate both mode and checksum.
GIT_SHA=$(runuser -u joshan -- git -C "$PLATFORM" show "$HEAD:governor/job_records.py" | sha256sum | awk '{print $1}')
SOURCE_SHA=$(sha256sum "$SOURCE" | awk '{print $1}')
[[ "$GIT_SHA" == "$SOURCE_SHA" ]] || fail canonical_helper_checksum_mismatch

SOURCE_MODE=$(stat -c '%a' "$SOURCE")
if (( (8#$SOURCE_MODE & 8#022) != 0 )); then
  chmod 0644 "$SOURCE"
  echo "CANONICAL_HELPER_MODE_REPAIRED=YES"
fi
SOURCE_MODE=$(stat -c '%a' "$SOURCE")
(( (8#$SOURCE_MODE & 8#022) == 0 )) || fail canonical_helper_group_or_other_writable
[[ $(sha256sum "$SOURCE" | awk '{print $1}') == "$GIT_SHA" ]] || fail canonical_helper_checksum_changed_after_mode_repair

echo "CANONICAL_HELPER_SOURCE_SAFETY=PASS"

install -d -o root -g root -m 0750 "$AUDIT_DIR"
if [[ -f "$LIVE" && ! -L "$LIVE" ]]; then
  HAD_LIVE=1
  install -o root -g root -m 0600 "$LIVE" "$BACKUP"
fi

TMP=$(mktemp /usr/local/libexec/.job_records.py.step11.XXXXXX)
trap 'rm -f "$TMP"' EXIT
install -o root -g root -m 0644 "$SOURCE" "$TMP"
mv -f "$TMP" "$LIVE"
trap - EXIT

[[ $(stat -c '%u:%g:%a' "$LIVE") == '0:0:644' ]] || false
[[ $(sha256sum "$LIVE" | awk '{print $1}') == "$SOURCE_SHA" ]] || false
python3 -m py_compile "$LIVE"

systemctl restart "$SERVICE"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8790/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
systemctl is-active --quiet "$SERVICE"
curl -fsS --max-time 5 http://127.0.0.1:8790/health >/dev/null

bash "$PLATFORM/scripts/diagnose-step11-live-terminal-policy.sh" | tee /tmp/lifeos-step11-diagnostic.out
grep -qx 'LIVE_TERMINAL_CONTRACT=PASS' /tmp/lifeos-step11-diagnostic.out
grep -qx 'LIVE_MODULE_SYNC=PASS' /tmp/lifeos-step11-diagnostic.out
grep -qx 'FINAL_STATUS=PASS' /tmp/lifeos-step11-diagnostic.out

python3 - "$AUDIT" "$HEAD" "$SOURCE_SHA" <<'PY'
import datetime,json,os,sys,tempfile
path, commit, digest = sys.argv[1:]
payload = {
    'schema_version': 1,
    'step': 11,
    'status': 'PASS',
    'source_commit': commit,
    'job_records_sha256': digest,
    'live_path': '/usr/local/libexec/job_records.py',
    'service': 'lifeos-autonomous-agent.service',
    'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'terminal_contract': {
        'PASS': 'stop',
        'BLOCKED': 'stop',
        'REPEATED_FAILURE': 'stop',
        'ITERATION_LIMIT': 'stop',
        'NON_TERMINAL': 'retry',
    },
}
dirname=os.path.dirname(path)
fd,tmp=tempfile.mkstemp(prefix='.step11.',dir=dirname,text=True)
try:
    with os.fdopen(fd,'w') as f:
        json.dump(payload,f,sort_keys=True,indent=2)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.chown(tmp,0,0); os.chmod(tmp,0o600); os.replace(tmp,path)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
PY

trap - ERR
rm -f "$BACKUP" /tmp/lifeos-step11-diagnostic.out

echo "STEP_11=PASS"
echo "SOURCE_COMMIT=$HEAD"
echo "LIVE_MODULE_SYNC=PASS"
echo "PASS_STOP=PASS"
echo "GENUINE_BLOCKED_STOP=PASS"
echo "REPEATED_FAILURE_STOP=PASS"
echo "ITERATION_LIMIT_STOP=PASS"
echo "NON_TERMINAL_RETRY=PASS"
echo "AUTONOMOUS_AGENT_HEALTH=PASS"
echo "AUDIT_EVIDENCE=$AUDIT"
echo "NEXT_REQUIRED=step11_closed"
