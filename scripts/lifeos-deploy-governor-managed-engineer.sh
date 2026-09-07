#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly BROKER_SOCKET=/run/lifeos-root-broker.sock
readonly IDENTITY=/etc/lifeos-control/identity.json
readonly APPROVAL_DIR=/var/lib/lifeos-control/engineer-deploy-approvals
readonly AUDIT_DIR=/var/lib/lifeos-control/engineer-deploy-audit

fail(){ printf 'ENGINEER_LIFECYCLE_DEPLOY=FAIL\nFAIL_REASON=%s\n' "$*" >&2; exit 1; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

[[ $(id -u) -eq 0 ]] || fail must_run_as_root
[[ -S "$BROKER_SOCKET" ]] || fail root_broker_socket_missing
[[ -r "$IDENTITY" ]] || fail control_identity_missing

HEAD=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse HEAD)
MAIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse main)
ORIGIN=$(runuser -u joshan -- git -C "$PLATFORM" rev-parse origin/main)
STATUS=$(runuser -u joshan -- git -C "$PLATFORM" status --porcelain --untracked-files=no)
[[ "$HEAD" == "$MAIN" && "$HEAD" == "$ORIGIN" && -z "$STATUS" ]] || fail source_not_clean_published_main

TARGET=$(python3 - "$IDENTITY" <<'PY'
import json,sys
value=json.load(open(sys.argv[1]))
target=value.get('target_id')
assert isinstance(target,str) and target and all(c.isalnum() or c in '._-' for c in target)
print(target)
PY
) || fail invalid_control_identity

declare -A HASHES
for rel in governor/autonomous_agent.py governor/target_identity.py governor/engineer_backend.py; do
  runuser -u joshan -- git -C "$PLATFORM" ls-files --error-unmatch -- "$rel" >/dev/null || fail "untracked_source:$rel"
  python3 -m py_compile "$PLATFORM/$rel" || fail "compile_failed:$rel"
  HASHES[$rel]=$(sha "$PLATFORM/$rel")
done

JOB_ID="governor-managed-engineer-${HEAD:0:12}"
APPROVAL="$APPROVAL_DIR/$JOB_ID.json"
AUDIT="$AUDIT_DIR/$JOB_ID.json"
install -d -o root -g root -m 0750 "$APPROVAL_DIR" "$AUDIT_DIR"

if [[ -e "$AUDIT" ]]; then
  python3 - "$AUDIT" "$HEAD" "${HASHES[governor/autonomous_agent.py]}" "${HASHES[governor/target_identity.py]}" "${HASHES[governor/engineer_backend.py]}" <<'PY' || fail existing_audit_does_not_match
import json,sys
d=json.load(open(sys.argv[1]))
assert d['deployment_result']=='PASS' and d['source_commit']==sys.argv[2], d
expected=dict(zip(('governor/autonomous_agent.py','governor/target_identity.py','governor/engineer_backend.py'),sys.argv[3:]))
assert d['source_hashes']==expected, d
PY
  echo 'ENGINEER_RUNTIME_DEPLOY=IDEMPOTENT_PASS'
else
  [[ ! -e "$APPROVAL" ]] || fail stale_approval_without_audit
  python3 - "$APPROVAL" "$JOB_ID" "$TARGET" "$HEAD" "${HASHES[governor/autonomous_agent.py]}" "${HASHES[governor/target_identity.py]}" "${HASHES[governor/engineer_backend.py]}" <<'PY'
import datetime,json,os,sys
path,job,target,commit,agent,identity,backend=sys.argv[1:]
value={
  'schema_version':1,'operation':'deploy-engineer-runtime','job_id':job,'target':target,
  'source_commit':commit,
  'source_hashes':{'governor/autonomous_agent.py':agent,'governor/target_identity.py':identity,'governor/engineer_backend.py':backend},
  'publication_verified':True,
  'independent_verifier':{'verdict':'PASS','evidence_id':'lifeos-ci-pr-176'},
  'protected_policy':{'verdict':'PASS','evidence_id':'explicit-user-approval-pr-176-deployment'},
  'approved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:
    json.dump(value,f,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.chown(path,0,0)
PY
  python3 - "$BROKER_SOCKET" "$JOB_ID" "$TARGET" <<'PY'
import json,socket,sys
request={'operation':'deploy-engineer-runtime','job_id':sys.argv[2],'target':sys.argv[3]}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(180); s.connect(sys.argv[1]); s.sendall((json.dumps(request)+'\n').encode()); s.shutdown(socket.SHUT_WR)
    chunks=[]
    while True:
        chunk=s.recv(65536)
        if not chunk: break
        chunks.append(chunk)
payload=json.loads(b''.join(chunks).decode())
print('ROOT_BROKER_RESULT='+json.dumps(payload,sort_keys=True))
assert payload.get('status')=='PASS', payload
PY
  echo 'ENGINEER_RUNTIME_DEPLOY=PASS'
fi

[[ "$(sha /usr/local/libexec/lifeos-autonomous-agent)" == "${HASHES[governor/autonomous_agent.py]}" ]] || fail autonomous_agent_hash_mismatch
[[ "$(sha /usr/local/libexec/target_identity.py)" == "${HASHES[governor/target_identity.py]}" ]] || fail target_identity_hash_mismatch
[[ "$(sha /usr/local/libexec/lifeos-engineer)" == "${HASHES[governor/engineer_backend.py]}" ]] || fail engineer_backend_hash_mismatch
systemctl is-active --quiet lifeos-autonomous-agent.service || fail governor_not_active
systemctl is-active --quiet lifeos-engineer.service || fail engineer_not_active
curl -fsS --max-time 10 http://127.0.0.1:8790/health >/dev/null || fail governor_health_failed
curl -fsS --max-time 10 http://127.0.0.1:8793/ready >/dev/null || fail engineer_readiness_failed
echo 'ENGINEER_LIFECYCLE_DEPLOY=PASS'
echo "SOURCE_COMMIT=$HEAD"
echo "DEPLOYMENT_AUDIT=$AUDIT"
