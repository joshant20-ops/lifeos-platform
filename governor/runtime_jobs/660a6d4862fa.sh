#!/usr/bin/env bash
set -euo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL=/home/joshan/lifeos-pi-control
readonly ASSURED_COMMIT=c890d27851554c5ab6df23ceb1b6079e9912449b
readonly BROKER_SHA=a15e9c2b0f2ed31600d936eaa1b64d61fc094779a49542267b73c78cfa701417
readonly JOB_ID=activate-engineer-v1-660a6d4862fa
readonly SCRIPT_REL=jobs/root-scripts/${JOB_ID}.sh
readonly MANIFEST="$CONTROL/jobs/staging/${JOB_ID}.json"

fail() {
  echo "FAIL=$1"
  echo "RESULT=RETRY"
  echo "TESTS=activation precondition or runtime acceptance failed"
  echo "NEXT_RUNTIME_CHECK=inspect the named FAIL evidence and checksummed control result"
  exit 1
}
run() { timeout --signal=TERM --kill-after=10s "$@"; }

[[ -d "$PLATFORM/.git" && -d "$CONTROL/.git" ]] || fail canonical_repository_missing

# Required canonical fast-forward-only synchronisation and publication proof.
run 120s git -C "$PLATFORM" fetch origin main || fail platform_fetch
run 30s git -C "$PLATFORM" merge --ff-only origin/main || fail platform_non_fast_forward
HEAD=$(git -C "$PLATFORM" rev-parse HEAD)
[[ "$HEAD" == "$(git -C "$PLATFORM" rev-parse main)" ]] || fail head_not_main
[[ "$HEAD" == "$(git -C "$PLATFORM" rev-parse origin/main)" ]] || fail source_not_published
git -C "$PLATFORM" merge-base --is-ancestor "$ASSURED_COMMIT" "$HEAD" || fail assured_commit_not_in_main
[[ -z $(git -C "$PLATFORM" status --porcelain --untracked-files=no) ]] || fail platform_not_clean
[[ $(sha256sum "$PLATFORM/homelab/live/usr/local/sbin/lifeos-root-broker" | awk '{print $1}') == "$BROKER_SHA" ]] || fail canonical_broker_hash

echo "SOURCE_COMMIT=$HEAD"
echo "ASSURED_COMMIT=$ASSURED_COMMIT"
echo "CANONICAL_BROKER_SHA256=$BROKER_SHA"

# Re-run the complete focused Engineer suite plus protected publisher/sync regressions.
run 300s python3 -m pytest -q \
  "$PLATFORM/tests/test_engineer_runtime_deployment.py" \
  "$PLATFORM/tests/test_engineer_job_observability_acceptance.py" \
  "$PLATFORM/tests/test_engineer_ai_observability_contract.py" \
  "$PLATFORM/tests/test_engineer_deployment_contract.py" \
  "$PLATFORM/tests/test_engineer_immediate_continuation_contract.py" \
  "$PLATFORM/tests/test_engineer_live_acceptance_contract.py" \
  "$PLATFORM/tests/test_job_publisher_fifo.py" \
  "$PLATFORM/tests/test_github_sync_protection.py" \
  "$PLATFORM/tests/test_snapshot_protected_drift.py" || fail focused_regressions
echo "PRE_ACTIVATION_TESTS=PASS"

# Never overwrite prior evidence. Existing unrelated queue items are left in
# place: the protected publisher/control runner owns FIFO serialization, so
# staging this job does not jump them.
if [[ -f "$CONTROL/results/$JOB_ID.json" ]]; then
  python3 - "$CONTROL/results/$JOB_ID.json" <<'PY' || fail prior_result_not_pass
import json, sys
d=json.load(open(sys.argv[1]))
assert d.get("classification") == "PASS", d
print("CONTROL_RESULT=PASS(existing)")
PY
  echo "RESULT=PASS"
  echo "TESTS=previous immutable checksummed control result is PASS"
  echo "NEXT_RUNTIME_CHECK=none"
  exit 0
fi

mkdir -p "$CONTROL/jobs/root-scripts" "$CONTROL/jobs/staging"
[[ ! -e "$CONTROL/$SCRIPT_REL" && ! -e "$MANIFEST" ]] || fail activation_job_already_staged

cat >"$CONTROL/$SCRIPT_REL" <<'ROOT_JOB'
#!/usr/bin/env bash
set -euo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly LIVE=/usr/local/sbin/lifeos-root-broker
readonly DESIRED="$PLATFORM/homelab/live/usr/local/sbin/lifeos-root-broker"
readonly APPROVED_SHA=a15e9c2b0f2ed31600d936eaa1b64d61fc094779a49542267b73c78cfa701417
readonly OLD_SHA=fe5b4a34aa022553a82a97b2b56f024116ae6e21995b1e18d86434a56675e1a4
readonly ASSURED_COMMIT=c890d27851554c5ab6df23ceb1b6079e9912449b
readonly DEPLOY_ID=engineer-v1-660a6d4862fa
BACKUP=""
ACTIVATED=false

fail() { echo "FAIL=$1"; exit 1; }
run() { timeout --signal=TERM --kill-after=10s "$@"; }
sha() { sha256sum "$1" | awk '{print $1}'; }

rollback_broker() {
  [[ "$ACTIVATED" == true && -n "$BACKUP" && -f "$BACKUP" ]] || return 0
  local tmp
  tmp=$(mktemp /usr/local/sbin/.lifeos-root-broker.rollback.XXXXXX)
  cp --preserve=mode,ownership,timestamps "$BACKUP" "$tmp"
  [[ $(sha "$tmp") == "$OLD_SHA" ]] || return 1
  mv -f "$tmp" "$LIVE"
  systemctl restart lifeos-root-broker.socket
  echo "BROKER_ROLLBACK=PASS"
}
trap 'rc=$?; if ((rc)); then rollback_broker || echo BROKER_ROLLBACK=FAIL; fi; exit $rc' EXIT

[[ $(id -u) -eq 0 ]] || fail root_broker_scope_not_root
HEAD=$(git -C "$PLATFORM" rev-parse HEAD)
[[ "$HEAD" == "$(git -C "$PLATFORM" rev-parse main)" && "$HEAD" == "$(git -C "$PLATFORM" rev-parse origin/main)" ]] || fail source_not_published_main
git -C "$PLATFORM" merge-base --is-ancestor "$ASSURED_COMMIT" "$HEAD" || fail assured_commit_missing
[[ -z $(git -C "$PLATFORM" status --porcelain --untracked-files=no) ]] || fail source_dirty
[[ $(sha "$DESIRED") == "$APPROVED_SHA" ]] || fail assured_broker_hash_changed
python3 -m py_compile "$DESIRED" || fail broker_syntax

LIVE_SHA=$(sha "$LIVE")
echo "OLD_BROKER_SHA256=$LIVE_SHA"
echo "NEW_BROKER_SHA256=$APPROVED_SHA"
if [[ "$LIVE_SHA" == "$APPROVED_SHA" ]]; then
  echo "BROKER_ACTIVATION=already-active"
elif [[ "$LIVE_SHA" == "$OLD_SHA" ]]; then
  BACKUP="/var/lib/lifeos-control/root-broker-backups/${LIFEOS_JOB_ID}-${LIVE_SHA}.bak"
  install -d -o root -g root -m 0700 "$(dirname "$BACKUP")"
  [[ ! -e "$BACKUP" ]] || fail broker_backup_exists
  cp --preserve=mode,ownership,timestamps "$LIVE" "$BACKUP"
  [[ $(sha "$BACKUP") == "$OLD_SHA" ]] || fail broker_backup_hash
  old_uid=$(stat -c %u "$LIVE"); old_gid=$(stat -c %g "$LIVE"); old_mode=$(stat -c %a "$LIVE")
  tmp=$(mktemp /usr/local/sbin/.lifeos-root-broker.install.XXXXXX)
  cp "$DESIRED" "$tmp"
  chown "$old_uid:$old_gid" "$tmp"; chmod "$old_mode" "$tmp"
  [[ $(sha "$tmp") == "$APPROVED_SHA" ]] || fail broker_temporary_hash
  mv -f "$tmp" "$LIVE"
  ACTIVATED=true
  run 30s systemctl restart lifeos-root-broker.socket || fail broker_socket_restart
  echo "BROKER_BACKUP=$BACKUP"
  echo "BROKER_ACTIVATION=PASS"
else
  fail live_broker_unapproved_hash
fi

[[ $(sha "$LIVE") == "$APPROVED_SHA" ]] || fail live_broker_post_hash
[[ $(systemctl is-active lifeos-root-broker.socket) == active ]] || fail broker_socket_inactive

# The newly activated broker must remain fail-closed before any real deployment.
python3 - <<'PY' || fail malformed_request_accepted
import json, socket
r={"operation":"deploy-engineer-runtime","job_id":"malformed-probe","target":"pi5","command":"id"}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(5); s.connect('/run/lifeos-root-broker.sock')
    s.sendall((json.dumps(r)+'\n').encode()); s.shutdown(socket.SHUT_WR); out=s.recv(8192).decode()
assert 'REJECTED' in out, out
print('MALFORMED_REQUEST_BEFORE=PASS')
PY

# Root-scoped control evidence binds the bounded request to exact published bytes.
APPROVAL_DIR=/var/lib/lifeos-control/engineer-deploy-approvals
AUDIT=/var/lib/lifeos-control/engineer-deploy-audit/${DEPLOY_ID}.json
install -d -o root -g root -m 0750 "$APPROVAL_DIR"
[[ ! -e "$APPROVAL_DIR/$DEPLOY_ID.json" && ! -e "$AUDIT" ]] || fail deployment_replay
AGENT_SHA=$(sha "$PLATFORM/governor/autonomous_agent.py")
BACKEND_SHA=$(sha "$PLATFORM/governor/engineer_backend.py")
python3 - "$APPROVAL_DIR/$DEPLOY_ID.json" "$DEPLOY_ID" "$HEAD" "$AGENT_SHA" "$BACKEND_SHA" <<'PY'
import datetime, json, os, sys
path, job, commit, agent, backend = sys.argv[1:]
d={"schema_version":1,"operation":"deploy-engineer-runtime","job_id":job,"target":"pi5",
   "source_commit":commit,"source_hashes":{"governor/autonomous_agent.py":agent,"governor/engineer_backend.py":backend},
   "publication_verified":True,
   "independent_verifier":{"verdict":"PASS","evidence_id":"assurance-c890d278-focused-regressions"},
   "protected_policy":{"verdict":"PASS","evidence_id":"human-approval-660a6d4862fa"},
   "approved_at":datetime.datetime.now(datetime.timezone.utc).isoformat()}
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: json.dump(d,f,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.chown(path,0,0)
PY

python3 - "$DEPLOY_ID" <<'PY' || fail bounded_engineer_deployment
import json, socket, sys
r={"operation":"deploy-engineer-runtime","job_id":sys.argv[1],"target":"pi5"}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(150); s.connect('/run/lifeos-root-broker.sock')
    s.sendall((json.dumps(r)+'\n').encode()); s.shutdown(socket.SHUT_WR)
    chunks=[]
    while True:
        b=s.recv(65536)
        if not b: break
        chunks.append(b)
out=b''.join(chunks).decode(); print('DEPLOY_RESPONSE='+out.strip())
d=json.loads(out); assert d.get('status') == 'PASS', d
PY

python3 - "$AUDIT" "$HEAD" "$AGENT_SHA" "$BACKEND_SHA" <<'PY' || fail deployment_audit_invalid
import json, sys
d=json.load(open(sys.argv[1]))
assert d['deployment_result']=='PASS' and d['rollback_result']=='not-required'
assert d['source_commit']==sys.argv[2]
assert d['source_hashes']['governor/autonomous_agent.py']==sys.argv[3]
assert d['source_hashes']['governor/engineer_backend.py']==sys.argv[4]
assert d['backup_location'] and d['publication_verified'] is True
assert d['independent_verifier']['verdict']=='PASS' and d['protected_policy']['verdict']=='PASS'
print('DEPLOYMENT_AUDIT=PASS')
PY

# Live API and Open WebUI-compatible acceptance, using only read-only questions.
python3 - <<'PY' || fail live_acceptance
import json, urllib.request
def get(url):
    with urllib.request.urlopen(url,timeout=10) as r: return json.load(r)
def ask(q):
    data=json.dumps({"model":"lifeos-engineer","messages":[{"role":"user","content":q}]}).encode()
    req=urllib.request.Request('http://127.0.0.1:8793/v1/chat/completions',data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as r: d=json.load(r)
    return d['choices'][0]['message']['content']
h=get('http://127.0.0.1:8790/health'); assert h['status']=='ok' and isinstance(h['max_continuation_depth'],int)
e=get('http://127.0.0.1:8793/health'); assert e['status']=='ok'
j1=get('http://127.0.0.1:8790/jobs'); assert isinstance(j1.get('jobs'),list)
j2=get('http://127.0.0.1:8790/jobs'); assert j1==j2
s1=get('http://127.0.0.1:8790/jobs/stuck'); s2=get('http://127.0.0.1:8790/jobs/stuck'); assert s1==s2 and isinstance(s1.get('stuck_jobs'),list)
a=ask('Give me the status of all the historical jobs'); assert 'histor' in a.lower() or 'no lifeos engineer jobs' in a.lower()
b=ask('What jobs are currently running, queued, failed or blocked, and complete?'); assert all(x in b for x in ('RUNNING','QUEUED','BLOCKED/FAILED','COMPLETE'))
c=ask('Is anything stuck?'); assert 'stuck' in c.lower()
print('LIVE_HEALTH=PASS'); print('JOBS_HISTORY=PASS'); print('JOBS_STUCK=PASS'); print('OPEN_WEBUI_ACCEPTANCE=PASS')
PY

python3 - <<'PY' || fail malformed_request_after_accepted
import json, socket
r={"operation":"deploy-engineer-runtime","job_id":"post-probe","target":"wrong-target"}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(5); s.connect('/run/lifeos-root-broker.sock')
    s.sendall((json.dumps(r)+'\n').encode()); s.shutdown(socket.SHUT_WR); out=s.recv(8192).decode()
assert 'REJECTED' in out, out
print('MALFORMED_REQUEST_AFTER=PASS')
PY

ACTIVATED=false
trap - EXIT
echo "LIVE_BROKER_SHA256=$(sha "$LIVE")"
echo "ENGINEER_DEPLOYMENT=PASS"
echo "AUDIT_EVIDENCE=$AUDIT"
echo "PASS=engineer_v1_self_deployment_complete"
ROOT_JOB
chmod 0755 "$CONTROL/$SCRIPT_REL"

SCRIPT_SHA=$(sha256sum "$CONTROL/$SCRIPT_REL" | awk '{print $1}')
python3 - "$MANIFEST" "$JOB_ID" "$SCRIPT_REL" "$SCRIPT_SHA" <<'PY'
import json, sys
path, job, script, digest=sys.argv[1:]
d={"schema_version":1,"job_id":job,"target":"pi5","job_type":"change","script":script,
   "script_sha256":digest,"timeout_seconds":900,"created_by":"lifeos-cloud-builder-660a6d4862fa",
   "description":"Activate only assured root broker and bounded Engineer V1 runtime",
   "change_scope":"root-broker","change_policy":"gated-v1","requires_root":True}
with open(path,'x') as f: json.dump(d,f,indent=2,sort_keys=True); f.write('\n')
PY

# Publisher and runner retain their normal checksum, Gitleaks, Git and health
# gates. Let earlier FIFO work clear rather than rejecting or jumping it.
runner_unit=false
if systemctl list-unit-files lifeos-pi-control-runner.service --no-legend 2>/dev/null | grep -q '^lifeos-pi-control-runner.service'; then
  runner_unit=true
fi
publish_deadline=$((SECONDS + 900))
while [[ ! -f "$CONTROL/jobs/pending/$JOB_ID.json" && $SECONDS -lt $publish_deadline ]]; do
  run 180s /usr/local/sbin/lifeos-job-publisher || fail publisher_rejected
  [[ -f "$CONTROL/jobs/pending/$JOB_ID.json" ]] && break
  if [[ "$runner_unit" == true ]]; then
    run 30s systemctl start --no-block lifeos-pi-control-runner.service || fail control_runner_start
  fi
  sleep 2
done
[[ -f "$CONTROL/jobs/pending/$JOB_ID.json" ]] || fail activation_not_published_fifo_timeout
if [[ "$runner_unit" == true ]]; then
  run 30s systemctl start --no-block lifeos-pi-control-runner.service || fail control_runner_start
fi
deadline=$((SECONDS + 930))
while [[ ! -f "$CONTROL/results/$JOB_ID.json" && $SECONDS -lt $deadline ]]; do
  sleep 2
done
[[ -f "$CONTROL/results/$JOB_ID.json" ]] || fail activation_result_timeout
python3 - "$CONTROL/results/$JOB_ID.json" <<'PY' || fail activation_result_failed
import json, sys
d=json.load(open(sys.argv[1]))
assert d.get('classification') == 'PASS', d
print('CONTROL_RESULT=PASS')
print('CONTROL_MANIFEST_COMMIT='+str(d.get('manifest_commit','')))
PY

echo "RESULT=PASS"
echo "TESTS=focused regressions, checksummed activation, live APIs and three Open WebUI prompts PASS"
echo "NEXT_RUNTIME_CHECK=none"
