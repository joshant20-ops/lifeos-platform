#!/usr/bin/env bash
set -euo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL=/home/joshan/lifeos-pi-control
readonly JOB_ID=activate-engineer-v1-660a6d4862fa
readonly MANIFEST="$CONTROL/jobs/staging/$JOB_ID.json"
readonly SCRIPT="$CONTROL/jobs/root-scripts/$JOB_ID.sh"
readonly BRIDGE=/usr/local/libexec/lifeos-control-job-submit-bridge
readonly ACTIVATOR="$PLATFORM/governor/runtime_jobs/d2dd520ff95b.sh"

fail() {
  echo "FAIL=$1"
  echo "RESULT=BLOCKED"
  echo "TESTS=permission-contract activation or resumed chain failed"
  echo "NEXT_RUNTIME_CHECK=review FAIL and journalctl -t lifeos-control-permission-repair"
  exit 1
}
run() { timeout --signal=TERM --kill-after=20s "$@"; }

if [[ $(id -u) -ne 0 ]]; then
  echo "HUMAN_ACTION_REQUIRED=On Pi5 run exactly: sudo $PLATFORM/governor/runtime_jobs/00a97b97be69.sh"
  echo "RESULT=BLOCKED"
  echo "TESTS=repository permission-contract tests passed; root-owned bridge activation and inode ACL repair await approval"
  echo "NEXT_RUNTIME_CHECK=sudo $PLATFORM/governor/runtime_jobs/00a97b97be69.sh"
  exit 20
fi

[[ -d "$PLATFORM/.git" && -d "$CONTROL/.git" ]] || fail canonical_repository_missing
[[ -f "$MANIFEST" && ! -L "$MANIFEST" && -f "$SCRIPT" && ! -L "$SCRIPT" ]] || fail accepted_artifacts_missing_or_unsafe

echo "INSPECTION=accepted artifacts and bounded roots"
for path in "$MANIFEST" "$SCRIPT" \
  "$CONTROL/jobs/staging" "$CONTROL/jobs/root-scripts" \
  "$CONTROL/jobs/change-scripts" "$CONTROL/jobs/scripts"; do
  stat -c 'METADATA=%n owner=%U(%u) group=%G(%g) mode=%a type=%F' "$path"
  getfacl -cp -- "$path" | sed 's/^/ACL=/'
done
echo "INSPECTION=units and identities"
systemctl cat lifeos-control-job-submit.socket lifeos-control-job-submit@.service
systemctl show lifeos-control-job-submit@.service -p User -p Group -p SupplementaryGroups -p ReadWritePaths --no-pager
systemctl show lifeos-job-publisher.service lifeos-pi-control-runner.service -p User -p Group -p ExecStart --no-pager
getent passwd lifeos-control-submit | awk -F: '{print "BRIDGE_ACCOUNT=" $1 " uid=" $3 " gid=" $4 " home=" $6 " shell=" $7}'
awk -F= '$1=="LIFEOS_SUBMIT_ALLOWED_UID" {print "ENGINEER_CALLER_UID=" $2}' /etc/lifeos-control/control-job-submit.conf
echo "PERMISSION_MODEL=bridge:create-only-four-roots publisher:read-staged runner:policy-read engineer:socket-only all-others:none"

# Prove the immutable staged bytes are exactly the approved package.  No file
# contents are emitted.  Duplicates make repair fail closed.
tmpdir=$(mktemp -d)
trap 'rm -rf -- "$tmpdir"' EXIT
awk '/^cat >"\$CONTROL\/\$SCRIPT_REL" <<'"'"'ROOT_JOB'"'"'$/{copy=1;next} /^ROOT_JOB$/{copy=0} copy' \
  "$PLATFORM/governor/runtime_jobs/660a6d4862fa.sh" >"$tmpdir/approved.sh"
[[ -s "$tmpdir/approved.sh" ]] || fail approved_payload_extract
approved_sha=$(sha256sum "$tmpdir/approved.sh" | awk '{print $1}')
actual_sha=$(sha256sum "$SCRIPT" | awk '{print $1}')
[[ "$actual_sha" == "$approved_sha" ]] || fail staged_script_not_approved_bytes
python3 - "$MANIFEST" "$JOB_ID" "$approved_sha" <<'PY' || fail staged_manifest_not_approved
import json, sys
path, job, digest = sys.argv[1:]
actual=json.load(open(path))
expected={"schema_version":1,"job_id":job,"target":"pi5","job_type":"change",
 "script":f"jobs/root-scripts/{job}.sh","script_sha256":digest,"timeout_seconds":900,
 "created_by":"lifeos-cloud-builder-660a6d4862fa",
 "description":"Activate only assured root broker and bounded Engineer V1 runtime",
 "change_scope":"root-broker","change_policy":"gated-v1","requires_root":True}
assert actual == expected
print("ACCEPTED_MANIFEST_MATCH=PASS")
PY
for candidate in "$CONTROL/jobs/pending/$JOB_ID.json" "$CONTROL/results/$JOB_ID.json"; do
  [[ ! -e "$candidate" ]] || fail accepted_job_duplicate
done
compgen -G "$CONTROL/jobs/archive/$JOB_ID.*" >/dev/null && fail accepted_job_archive_duplicate

# Activate root-owned trusted code/config. The bridge remains unprivileged and
# can write only its four systemd ReadWritePaths.
publisher_uid=$(id -u joshan)
install -o root -g root -m 0755 "$PLATFORM/homelab/live/usr/local/libexec/lifeos-control-job-submit-bridge" "$BRIDGE"
tmpconf=$(mktemp /etc/lifeos-control/.control-job-submit.conf.XXXXXX)
printf 'LIFEOS_SUBMIT_ALLOWED_UID=%s\nLIFEOS_SUBMIT_PUBLISHER_UID=%s\n' "$publisher_uid" "$publisher_uid" >"$tmpconf"
chown root:root "$tmpconf"; chmod 0644 "$tmpconf"
mv -f "$tmpconf" /etc/lifeos-control/control-job-submit.conf
systemctl daemon-reload
systemctl restart lifeos-control-job-submit.socket

# Repair metadata only on the two already verified regular inodes. Content,
# timestamps and replay state are not rewritten.
chmod 0750 "$SCRIPT"; setfacl -m "u:$publisher_uid:r-x" "$SCRIPT"
chmod 0640 "$MANIFEST"; setfacl -m "u:$publisher_uid:r--" "$MANIFEST"
runuser -u joshan -- test -r "$MANIFEST" || fail publisher_manifest_unreadable
runuser -u joshan -- test -r "$SCRIPT" || fail publisher_script_unreadable
[[ $(sha256sum "$SCRIPT" | awk '{print $1}') == "$actual_sha" ]] || fail repair_changed_script
logger -p authpriv.notice -t lifeos-control-permission-repair \
  "job_id=$JOB_ID action=named-acl-repair reason=bridge-publisher-read-contract manifest_mode=0640 script_mode=0750 publisher_uid=$publisher_uid content_unchanged=true"
echo "PERMISSION_REPAIR_AUDIT=PASS"

# Existing protected activator owns FIFO publication, runner execution, broker
# hash verification, bounded deployment, health/history/stuck and prompt checks.
run 2200s "$ACTIVATOR" || fail resumed_chain
echo "RESULT=PASS"
echo "TESTS=fixed per-inode ACL contract, verified metadata-only repair, FIFO publisher/runner and full Engineer activation chain PASS"
echo "NEXT_RUNTIME_CHECK=none"
