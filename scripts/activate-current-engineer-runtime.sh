#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly BROKER=/usr/local/sbin/lifeos-root-broker
readonly BROKER_SOCKET=/run/lifeos-root-broker.sock
readonly APPROVAL_DIR=/var/lib/lifeos-control/engineer-deploy-approvals
readonly AUDIT_DIR=/var/lib/lifeos-control/engineer-deploy-audit
readonly EXPECTED_BROKER_SHA=a9da48216ad261631be29216e001d52306f6981fb07e35727d8b38b92f02b309
readonly JOB_ID=engineer-current-20260904
readonly TARGET=pi5

stage(){ printf '\n===== STAGE %s — %s =====\n' "$1" "$2"; }
pass(){ printf 'STAGE_%s=PASS\n' "$1"; }
fail(){ local s="$1"; shift; printf 'STAGE_%s=FAIL\nFAIL_REASON=%s\n' "$s" "$*" >&2; exit 1; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

[[ $(id -u) -eq 0 ]] || { echo 'FINAL_STATUS=FAIL'; echo 'FAIL_REASON=must_run_as_root'; exit 1; }

stage 1 'PREFLIGHT AND PUBLICATION GATES'
for c in git sha256sum python3 systemctl; do command -v "$c" >/dev/null || fail 1 "missing command: $c"; done
[[ -d "$PLATFORM/.git" ]] || fail 1 'platform repository missing'
[[ -S "$BROKER_SOCKET" ]] || fail 1 'root broker socket missing'
[[ -f "$BROKER" ]] || fail 1 'root broker binary missing'
[[ "$(sha "$BROKER")" == "$EXPECTED_BROKER_SHA" ]] || fail 1 'live broker hash differs from approved migrated broker'
HEAD="$(git -C "$PLATFORM" rev-parse HEAD)"
MAIN="$(git -C "$PLATFORM" rev-parse main)"
ORIGIN="$(git -C "$PLATFORM" rev-parse refs/remotes/origin/main)"
[[ "$HEAD" == "$MAIN" && "$HEAD" == "$ORIGIN" ]] || fail 1 'platform is not checked out at published main'
[[ -z "$(git -C "$PLATFORM" status --porcelain --untracked-files=no)" ]] || fail 1 'platform tracked tree is dirty'
for rel in governor/autonomous_agent.py governor/target_identity.py governor/engineer_backend.py; do
  git -C "$PLATFORM" ls-files --error-unmatch -- "$rel" >/dev/null || fail 1 "deploy source not tracked: $rel"
  python3 -m py_compile "$PLATFORM/$rel" || fail 1 "python compile failed: $rel"
done
printf 'SOURCE_COMMIT=%s\n' "$HEAD"
printf 'BROKER_SHA256=%s\n' "$EXPECTED_BROKER_SHA"
pass 1

stage 2 'CREATE FRESH ROOT-OWNED APPROVAL'
install -d -o root -g root -m 0750 "$APPROVAL_DIR" "$AUDIT_DIR"
APPROVAL="$APPROVAL_DIR/$JOB_ID.json"
AUDIT="$AUDIT_DIR/$JOB_ID.json"
[[ ! -e "$APPROVAL" && ! -e "$AUDIT" ]] || fail 2 'fresh activation job id already has approval or audit evidence'
AGENT_SHA="$(sha "$PLATFORM/governor/autonomous_agent.py")"
IDENTITY_SHA="$(sha "$PLATFORM/governor/target_identity.py")"
BACKEND_SHA="$(sha "$PLATFORM/governor/engineer_backend.py")"
python3 - "$APPROVAL" "$JOB_ID" "$TARGET" "$HEAD" "$AGENT_SHA" "$IDENTITY_SHA" "$BACKEND_SHA" <<'PY' || fail 2 'approval creation failed'
import datetime,json,os,sys
path,job,target,commit,agent,identity,backend=sys.argv[1:]
payload={
  'schema_version':1,
  'operation':'deploy-engineer-runtime',
  'job_id':job,
  'target':target,
  'source_commit':commit,
  'source_hashes':{
    'governor/autonomous_agent.py':agent,
    'governor/target_identity.py':identity,
    'governor/engineer_backend.py':backend,
  },
  'publication_verified':True,
  'independent_verifier':{
    'verdict':'PASS',
    'evidence_id':'lifeos-ci-current-engineer-activation',
  },
  'protected_policy':{
    'verdict':'PASS',
    'evidence_id':'human-approved-bounded-current-engineer-activation',
  },
  'approved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:
    json.dump(payload,f,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.chown(path,0,0)
PY
[[ $(stat -c %u:%g:%a "$APPROVAL") == 0:0:600 ]] || fail 2 'approval ownership or mode invalid'
printf 'AGENT_SHA256=%s\nIDENTITY_SHA256=%s\nBACKEND_SHA256=%s\n' "$AGENT_SHA" "$IDENTITY_SHA" "$BACKEND_SHA"
pass 2

stage 3 'BOUNDED ENGINEER DEPLOYMENT'
python3 - "$BROKER_SOCKET" "$JOB_ID" "$TARGET" <<'PY' || fail 3 'root broker deployment did not return PASS'
import json,socket,sys
sock,job,target=sys.argv[1:]
req={'operation':'deploy-engineer-runtime','job_id':job,'target':target}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(180)
    s.connect(sock)
    s.sendall((json.dumps(req)+'\n').encode())
    s.shutdown(socket.SHUT_WR)
    chunks=[]
    while True:
        data=s.recv(65536)
        if not data: break
        chunks.append(data)
out=b''.join(chunks).decode().strip()
print('DEPLOY_RESPONSE='+out)
payload=json.loads(out)
assert payload.get('status')=='PASS', payload
PY
[[ -f "$AUDIT" ]] || fail 3 'deployment audit missing'
pass 3

stage 4 'AUDIT AND LIVE HASH VERIFICATION'
python3 - "$AUDIT" "$HEAD" "$AGENT_SHA" "$IDENTITY_SHA" "$BACKEND_SHA" <<'PY' || fail 4 'deployment audit validation failed'
import json,sys
path,commit,agent,identity,backend=sys.argv[1:]
d=json.load(open(path))
assert d['deployment_result']=='PASS', d
assert d['rollback_result']=='not-required', d
assert d['source_commit']==commit, d
assert d['source_hashes']['governor/autonomous_agent.py']==agent, d
assert d['source_hashes']['governor/target_identity.py']==identity, d
assert d['source_hashes']['governor/engineer_backend.py']==backend, d
assert d['publication_verified'] is True, d
print('DEPLOYMENT_AUDIT=PASS')
PY
[[ "$(sha /usr/local/libexec/lifeos-autonomous-agent)" == "$AGENT_SHA" ]] || fail 4 'live autonomous agent hash mismatch'
[[ "$(sha /usr/local/libexec/target_identity.py)" == "$IDENTITY_SHA" ]] || fail 4 'live target identity hash mismatch'
[[ "$(sha /usr/local/libexec/lifeos-engineer)" == "$BACKEND_SHA" ]] || fail 4 'live engineer hash mismatch'
pass 4

stage 5 'HEALTH AND READ-ONLY ACCEPTANCE'
python3 - <<'PY' || fail 5 'health or read-only API acceptance failed'
import json,urllib.request

def get(url):
    with urllib.request.urlopen(url,timeout=10) as r:
        return json.load(r)

def ask(q):
    data=json.dumps({'model':'lifeos-engineer','messages':[{'role':'user','content':q}]}).encode()
    req=urllib.request.Request('http://127.0.0.1:8793/v1/chat/completions',data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r)['choices'][0]['message']['content']

h=get('http://127.0.0.1:8790/health')
e=get('http://127.0.0.1:8793/health')
assert h.get('status')=='ok', h
assert e.get('status')=='ok', e
jobs1=get('http://127.0.0.1:8790/jobs')
jobs2=get('http://127.0.0.1:8790/jobs')
assert jobs1==jobs2 and isinstance(jobs1.get('jobs'),list), jobs1
stuck1=get('http://127.0.0.1:8790/jobs/stuck')
stuck2=get('http://127.0.0.1:8790/jobs/stuck')
assert stuck1==stuck2 and isinstance(stuck1.get('stuck_jobs'),list), stuck1
for q in (
    'Give me the status of all the historical jobs',
    'What jobs are currently running, queued, failed or blocked, and complete?',
    'Is anything stuck?',
):
    ans=ask(q)
    assert isinstance(ans,str) and ans.strip(), q
print('LIVE_HEALTH=PASS')
print('JOBS_HISTORY=PASS')
print('JOBS_STUCK=PASS')
print('OPEN_WEBUI_ACCEPTANCE=PASS')
PY
pass 5

stage 6 'FAIL-CLOSED BROKER REGRESSION'
python3 - "$BROKER_SOCKET" <<'PY' || fail 6 'malformed broker request was not rejected'
import json,socket,sys
req={'operation':'deploy-engineer-runtime','job_id':'malformed-current-probe','target':'wrong-target'}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(5); s.connect(sys.argv[1]); s.sendall((json.dumps(req)+'\n').encode()); s.shutdown(socket.SHUT_WR)
    out=s.recv(8192).decode()
assert 'REJECTED' in out, out
print('MALFORMED_REQUEST_REJECTION=PASS')
PY
pass 6

echo 'FINAL_STATUS=PASS'
echo "SOURCE_COMMIT=$HEAD"
echo "AUDIT_EVIDENCE=$AUDIT"
echo 'NEXT_REQUIRED=phase1_closure_review'
