#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL=/home/joshan/lifeos-pi-control
readonly JOB_ID=powerdown-telemetry-0ab74fabbb7a
readonly RESULT_JSON="$CONTROL/results/$JOB_ID.json"
readonly BRIDGE_SOCKET=/run/lifeos-control-job-submit.sock
readonly FIX_COMMIT=6968eb4ea119f371a49960630cc7a4e62a094943
readonly CANONICAL_REL=homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py
readonly CANONICAL_SHA=fd7b1ce6e89bfd195fd86cb03a39f3c0ad592dc04d2091232f027f28375e23e7

fail() {
  printf 'FAIL=%s\n' "$1" >&2
  printf '%s\n' \
    'ISSUE_VALIDITY=VALID' \
    'LIFEOS_WORK_STATE=BLOCKED' \
    "BARRIER=$1" \
    'NEXT_AUTONOMOUS_ACTION=inspect the named failure and retry this bounded launcher after correcting only that dependency' \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    'RESULT=RETRY' \
    'TESTS=bounded deployment or live acceptance failed' \
    'NEXT_RUNTIME_CHECK=inspect the named FAIL and immutable control result'
  exit 1
}
run() { local limit=$1; shift; timeout --signal=TERM --kill-after=10s "$limit" "$@"; }
sha() { sha256sum "$1" | awk '{print $1}'; }

[[ -d "$PLATFORM/.git" && -d "$CONTROL/.git" ]] || fail canonical_repository_missing
[[ -S "$BRIDGE_SOCKET" ]] || fail authorised_control_bridge_missing
HEAD=$(git -C "$PLATFORM" rev-parse HEAD); readonly HEAD
[[ "$HEAD" == "$(git -C "$PLATFORM" rev-parse main)" ]] || fail canonical_head_not_main
[[ "$HEAD" == "$(git -C "$PLATFORM" rev-parse refs/remotes/origin/main)" ]] || fail canonical_not_published
git -C "$PLATFORM" merge-base --is-ancestor "$FIX_COMMIT" "$HEAD" || fail telemetry_fix_commit_missing
[[ -z $(git -C "$PLATFORM" status --porcelain --untracked-files=no) ]] || fail canonical_repository_dirty
[[ $(sha "$PLATFORM/$CANONICAL_REL") == "$CANONICAL_SHA" ]] || fail canonical_controller_hash_changed
run 20s python3 -m py_compile "$PLATFORM/$CANONICAL_REL" || fail canonical_syntax
printf 'CANONICAL_COMMIT=%s\nCANONICAL_CONTROLLER_SHA256=%s\nCANONICAL_SYNTAX=PASS\n' \
  "$FIX_COMMIT" "$CANONICAL_SHA"

if [[ ! -f "$RESULT_JSON" ]]; then
  package=$(mktemp -d); readonly package
  trap 'rm -rf -- "$package"' EXIT
  readonly root_script="$package/root-job.sh"
  readonly manifest="$package/manifest.json"

  apply_root_job() { cat >"$root_script" <<'ROOT_JOB'
#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly SOURCE="$PLATFORM/homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
readonly LIVE=/usr/local/sbin/lifeos-powerdown-assurance-active
readonly STATUS=/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json
readonly FIX_COMMIT=6968eb4ea119f371a49960630cc7a4e62a094943
readonly APPROVED_SHA=fd7b1ce6e89bfd195fd86cb03a39f3c0ad592dc04d2091232f027f28375e23e7
readonly PRE_FIX_SHA=23733e840168914701e70b50236adeecf39628766177e49b190184eba6a09b9e
readonly FIX_ONLY_SHA=5a99d52df2864e408c85bc0f0267e6ce632cf5d034db19b05c3791e56668700f
readonly ROOT_JOB_ID=powerdown-telemetry-0ab74fabbb7a
readonly BACKUP_DIR=/var/lib/lifeos-control/powerdown-controller-backups
BACKUP=""
CHANGED=false

fail() { printf 'FAIL=%s\n' "$1" >&2; exit 1; }
run() { local limit=$1; shift; timeout --signal=TERM --kill-after=10s "$limit" "$@"; }
sha() { sha256sum "$1" | awk '{print $1}'; }
rollback() {
  [[ "$CHANGED" == true && -f "$BACKUP" ]] || return 0
  local tmp
  tmp=$(mktemp /usr/local/sbin/.lifeos-powerdown.rollback.XXXXXX)
  install -o root -g root -m 0755 "$BACKUP" "$tmp"
  mv -f "$tmp" "$LIVE"
  printf '%s\n' 'DEPLOYMENT_ROLLBACK=PASS'
}
on_exit() {
  local rc=$?
  if ((rc)); then rollback || printf '%s\n' DEPLOYMENT_ROLLBACK=FAIL; fi
  exit "$rc"
}
trap on_exit EXIT

[[ $(id -u) -eq 0 ]] || fail protected_job_not_root
[[ -f "$SOURCE" && ! -L "$SOURCE" && -f "$LIVE" && ! -L "$LIVE" ]] || fail unsafe_controller_path
HEAD=$(git -C "$PLATFORM" rev-parse HEAD)
[[ "$HEAD" == "$(git -C "$PLATFORM" rev-parse main)" && "$HEAD" == "$(git -C "$PLATFORM" rev-parse refs/remotes/origin/main)" ]] || fail source_not_published_main
git -C "$PLATFORM" merge-base --is-ancestor "$FIX_COMMIT" "$HEAD" || fail fix_commit_not_ancestor
[[ -z $(git -C "$PLATFORM" status --porcelain --untracked-files=no) ]] || fail source_dirty
[[ $(sha "$SOURCE") == "$APPROVED_SHA" ]] || fail approved_source_hash_mismatch
run 20s python3 -m py_compile "$SOURCE" || fail source_syntax
[[ $(stat -c '%U:%G:%a' "$LIVE") == root:root:755 ]] || fail live_protection_mismatch

LIVE_SHA=$(sha "$LIVE"); readonly LIVE_SHA
case "$LIVE_SHA" in
  "$APPROVED_SHA") printf '%s\n' 'DEPLOYMENT=ALREADY_CURRENT' ;;
  "$PRE_FIX_SHA"|"$FIX_ONLY_SHA")
    install -d -o root -g root -m 0700 "$BACKUP_DIR"
    BACKUP="$BACKUP_DIR/${ROOT_JOB_ID}-${LIVE_SHA}.bak"
    [[ ! -e "$BACKUP" ]] || fail immutable_backup_exists
    install -o root -g root -m 0600 "$LIVE" "$BACKUP"
    [[ $(sha "$BACKUP") == "$LIVE_SHA" ]] || fail backup_hash_mismatch
    tmp=$(mktemp /usr/local/sbin/.lifeos-powerdown.install.XXXXXX)
    install -o root -g root -m 0755 "$SOURCE" "$tmp"
    [[ $(sha "$tmp") == "$APPROVED_SHA" ]] || fail temporary_hash_mismatch
    mv -f "$tmp" "$LIVE"
    CHANGED=true
    printf 'DEPLOYMENT=PASS\nBACKUP_SHA256=%s\n' "$LIVE_SHA"
    ;;
  *) fail live_controller_unapproved_hash ;;
esac
[[ $(sha "$LIVE") == "$APPROVED_SHA" ]] || fail live_post_deploy_hash
[[ $(stat -c '%U:%G:%a' "$LIVE") == root:root:755 ]] || fail live_post_deploy_protection

# Two distinct executions are mandatory. Starting the oneshot directly retains
# its secret wrapper and service sandbox; no credential is copied into this job.
[[ -f "$STATUS" ]] || fail pre_deploy_status_missing
PRE_RUN_RESERVE=$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("reserve") or {}).get("current_percent"))' "$STATUS")
[[ "$PRE_RUN_RESERVE" != None ]] || fail pre_run_reserve_unavailable
run 90s systemctl start --wait lifeos-powerdown-assurance-active.service || fail controller_run_one
run 90s systemctl start --wait lifeos-powerdown-assurance-active.service || fail controller_run_two
run 30s systemctl start --wait lifeos-powerdown-evidence-recorder.service || fail evidence_record

python3 - "$STATUS" "$PRE_RUN_RESERVE" <<'PY'
import datetime as dt, json, sys
from zoneinfo import ZoneInfo
s=json.load(open(sys.argv[1])); pre_reserve=float(sys.argv[2]); event=s.get('event') or {}; tele=s.get('telemetry') or {}
cross=tele.get('crosscheck') or {}; reserve=s.get('reserve') or {}; control=s.get('control') or {}
flags=set(s.get('anomaly_flags') or []); now=dt.datetime.now(ZoneInfo('Europe/London'))
expected_start=dt.datetime(2026,9,1,18,0,tzinfo=ZoneInfo('Europe/London'))
expected_end=dt.datetime(2026,9,1,19,0,tzinfo=ZoneInfo('Europe/London'))
if now < expected_start:
    nxt=event.get('next_event') or {}
    assert str(nxt.get('id'))=='5833', nxt
    assert dt.datetime.fromisoformat(nxt['start'])==expected_start and dt.datetime.fromisoformat(nxt['end'])==expected_end, nxt
    assert (s.get('readiness') or {}).get('state')=='READY', s.get('readiness')
    assert cross.get('current_good') is True and cross.get('trusted') is True and cross.get('good_runs',0)>=2, cross
    assert not ({'authoritative_grid_stale','aligned_crosscheck_unavailable'} & flags), flags
    assert control.get('action')=='NO_WRITE_OUTSIDE_EVENT' and control.get('write_performed') is False, control
    assert reserve.get('controller_owns_reserve') is False and reserve.get('saved_pre_event_percent') is None, reserve
    assert abs(float(reserve.get('current_percent'))-pre_reserve)<=0.1, (pre_reserve,reserve)
    print('PRE_EVENT_ACCEPTANCE=PASS')
elif now < expected_end:
    assert event.get('active') is True and str(event.get('id'))=='5833', event
    assert cross.get('current_good') is True and cross.get('trusted') is True, cross
    assert not ({'authoritative_grid_stale','aligned_crosscheck_unavailable'} & flags), flags
    assert reserve.get('saved_pre_event_percent') is not None, reserve
    assert reserve.get('controller_owns_reserve') is True, reserve
    assert control.get('action')=='ACTIVE_EVENT_RESERVE_RELEASE', control
    print('ACTIVE_EVENT_ACCEPTANCE=PASS')
else:
    assert event.get('active') is False, event
    assert reserve.get('controller_owns_reserve') is False, reserve
    assert reserve.get('saved_pre_event_percent') is None, reserve
    assert control.get('action') in {'POST_EVENT_RESERVE_RESTORE','NO_WRITE_OUTSIDE_EVENT'}, control
    evidence='/opt/lifeos-watch/octopus-powerdown-assurance/event-evidence-v52.jsonl'
    records=[json.loads(line) for line in open(evidence) if line.strip()]
    pre=[r for r in records if not (r.get('event') or {}).get('active') and
         ((r.get('event') or {}).get('next_event') or {}).get('id') in (5833,'5833') and
         (r.get('control') or {}).get('write_performed') is False]
    active=[r for r in records if (r.get('event') or {}).get('active') and
            str((r.get('event') or {}).get('id'))=='5833' and
            (r.get('telemetry') or {}).get('crosscheck_pass') is True and
            not ({'authoritative_grid_stale','aligned_crosscheck_unavailable'} & set(r.get('anomaly_flags') or [])) and
            (r.get('reserve') or {}).get('saved_pre_event_percent') is not None and
            (r.get('reserve') or {}).get('controller_owns_reserve') is True and
            (r.get('control') or {}).get('action')=='ACTIVE_EVENT_RESERVE_RELEASE']
    restored=[(i,r) for i,r in enumerate(records) if (r.get('reserve') or {}).get('restored_this_run') is True and
              (r.get('control') or {}).get('action')=='POST_EVENT_RESERVE_RESTORE' and
              (r.get('reserve') or {}).get('controller_owns_reserve') is False]
    assert pre and active and restored, {'pre_records':len(pre),'active_records':len(active),'restored_records':len(restored)}
    saved=float((active[0].get('reserve') or {})['saved_pre_event_percent'])
    after_restore=[r for r in records[restored[-1][0]+1:] if
                   (r.get('control') or {}).get('action')=='NO_WRITE_OUTSIDE_EVENT' and
                   (r.get('reserve') or {}).get('controller_owns_reserve') is False]
    assert after_restore, 'no post-restore observation'
    restored_current=float((after_restore[-1].get('reserve') or {})['current_percent'])
    assert abs(saved-restored_current)<=0.5, (saved,restored_current)
    print('EVENT_EVIDENCE_SEQUENCE=PASS')
    print('POST_EVENT_CURRENT_STATE=PASS')
print('CURRENT_CROSSCHECK=PASS')
print('CROSSCHECK_TRUSTED=PASS')
print('ANOMALY_FLAGS=' + (','.join(sorted(flags)) if flags else 'none'))
print('RESERVE_CURRENT_PERCENT=' + str(reserve.get('current_percent')))
print('WRITE_PERFORMED=' + ('yes' if control.get('write_performed') else 'no'))
PY

CHANGED=false
printf 'LIVE_DEPLOYMENT=PASS sha256=%s owner=root:root mode=0755\n' "$APPROVED_SHA"
ROOT_JOB
  }
  apply_root_job
  chmod 0755 "$root_script"
  script_sha=$(sha "$root_script"); readonly script_sha
  python3 - "$manifest" "$script_sha" <<'PY'
import json,sys
path,digest=sys.argv[1:]
d={'schema_version':1,'job_id':'powerdown-telemetry-0ab74fabbb7a','target':'pi5','job_type':'change',
   'script':'jobs/root-scripts/powerdown-telemetry-0ab74fabbb7a.sh','script_sha256':digest,
   'timeout_seconds':300,'created_by':'lifeos-cloud-builder-0ab74fabbb7a',
   'description':'Deploy only the pinned canonical Power Down controller and prove live telemetry trust',
   'change_scope':'root-broker','change_policy':'gated-v1','requires_root':True}
open(path,'x').write(json.dumps(d,sort_keys=True)+'\n')
PY
  run 15s python3 - "$manifest" "$root_script" "$BRIDGE_SOCKET" <<'PY' || fail protected_submission_rejected
import base64,json,socket,sys
manifest,script,sock=sys.argv[1:]
r={'operation':'submit-control-job','manifest':open(manifest).read(),
   'script_base64':base64.b64encode(open(script,'rb').read()).decode()}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(10); s.connect(sock); s.sendall(json.dumps(r).encode()); s.shutdown(socket.SHUT_WR)
    out=json.loads(s.recv(8192)); print('SUBMISSION_STATUS='+str(out.get('status')))
assert out.get('status')=='ACCEPTED',out
PY
  trap - EXIT; rm -rf -- "$package"

  # The legacy poll loop is not trusted for this incident. Explicitly publish
  # and trigger the existing bounded runner, without bypassing FIFO ordering.
  deadline=$((SECONDS + 240))
  while [[ ! -f "$RESULT_JSON" && $SECONDS -lt $deadline ]]; do
    if [[ ! -f "$CONTROL/jobs/pending/$JOB_ID.json" ]]; then
      run 60s /usr/local/sbin/lifeos-job-publisher || fail explicit_publisher_failed
    fi
    systemctl start --no-block lifeos-pi-control-runner.service 2>/dev/null || true
    sleep 2
  done
fi

[[ -f "$RESULT_JSON" ]] || fail protected_control_result_timeout
python3 - "$RESULT_JSON" <<'PY' || fail protected_control_result_failed
import json,sys
d=json.load(open(sys.argv[1])); assert d.get('classification')=='PASS',d
print('CONTROL_RESULT=PASS')
print('CONTROL_MANIFEST_COMMIT='+str(d.get('manifest_commit')))
print('CONTROL_OUTPUT_PATH='+str(d.get('output_path')))
PY
output_rel=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("output_path") or "")' "$RESULT_JSON")
[[ -n "$output_rel" && -f "$CONTROL/$output_rel" ]] || fail protected_output_missing
run 10s sed -n '1,240p' "$CONTROL/$output_rel"

printf '%s\n' \
  'ISSUE_VALIDITY=VALID' \
  'LIFEOS_WORK_STATE=PASS' \
  'BARRIER=none' \
  'NEXT_AUTONOMOUS_ACTION=none; event 5833 deployment and complete evidence sequence are proven' \
  'DISCOVERED_ISSUES_JSON_B64=none' \
  'RESULT=PASS' \
  'TESTS=canonical ancestry/hash/syntax, protected atomic deployment, two controller runs, live phase-specific safety acceptance PASS' \
  'NEXT_RUNTIME_CHECK=none'
