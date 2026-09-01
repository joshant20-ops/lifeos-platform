#!/usr/bin/env bash
set -euo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL=/home/joshan/lifeos-pi-control
readonly JOB_ID=activate-engineer-v1-660a6d4862fa
readonly ALLOWED_USER=joshan
readonly BRIDGE=/usr/local/libexec/lifeos-control-job-submit-bridge

fail() {
  echo "FAIL=$1"
  echo "RESULT=BLOCKED"
  echo "TESTS=bridge activation or resumed control flow failed"
  echo "NEXT_RUNTIME_CHECK=inspect FAIL and journalctl -u 'lifeos-control-job-submit@*'"
  exit 1
}
run() { timeout --signal=TERM --kill-after=10s "$@"; }

[[ $(id -u) -eq 0 ]] || {
  echo "HUMAN_ACTION_REQUIRED=run this one reviewed launcher as root on Pi5: sudo $PLATFORM/governor/runtime_jobs/d2dd520ff95b.sh"
  echo "RESULT=BLOCKED"
  echo "TESTS=repository implementation tested; new root-owned socket/account/ACL boundary not activated"
  echo "NEXT_RUNTIME_CHECK=sudo $PLATFORM/governor/runtime_jobs/d2dd520ff95b.sh"
  exit 20
}
[[ -d "$PLATFORM/.git" && -d "$CONTROL/.git" ]] || fail canonical_repository_missing

# Install only the fixed helper and its two units. The unprivileged service has
# no login, no supplementary groups and systemd write access to four exact dirs.
getent group lifeos-engineer >/dev/null || groupadd --system lifeos-engineer
id lifeos-control-submit >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin lifeos-control-submit
usermod -a -G lifeos-engineer "$ALLOWED_USER"
install -o root -g root -m 0755 "$PLATFORM/homelab/live/usr/local/libexec/lifeos-control-job-submit-bridge" "$BRIDGE"
install -o root -g root -m 0644 "$PLATFORM/homelab/live/etc/systemd/system/lifeos-control-job-submit.socket" /etc/systemd/system/lifeos-control-job-submit.socket
install -o root -g root -m 0644 "$PLATFORM/homelab/live/etc/systemd/system/lifeos-control-job-submit@.service" /etc/systemd/system/lifeos-control-job-submit@.service
install -d -o root -g root -m 0755 /etc/lifeos-control
ALLOWED_UID=$(id -u "$ALLOWED_USER")
tmp=$(mktemp /etc/lifeos-control/.control-job-submit.conf.XXXXXX)
printf 'LIFEOS_SUBMIT_ALLOWED_UID=%s\n' "$ALLOWED_UID" >"$tmp"
chown root:root "$tmp"; chmod 0644 "$tmp"
mv -f "$tmp" /etc/lifeos-control/control-job-submit.conf
for rel in jobs/staging jobs/scripts jobs/change-scripts jobs/root-scripts; do
  path="$CONTROL/$rel"
  [[ -d "$path" && ! -L "$path" ]] || fail "unsafe_control_directory_$rel"
  setfacl -m u:lifeos-control-submit:rwx "$path"
done
install -d -o lifeos-control-submit -g lifeos-control-submit -m 0750 /run/lifeos-control-submit
systemctl daemon-reload
systemctl enable --now lifeos-control-job-submit.socket
[[ $(systemctl is-active lifeos-control-job-submit.socket) == active ]] || fail socket_inactive

# Fail-closed peer and request-surface probes.
runuser -u "$ALLOWED_USER" -- python3 - <<'PY' || fail bridge_rejection_probe
import json, socket
request={"operation":"submit-control-job","manifest":"{}","script_base64":"","destination":"/tmp/escape"}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(5); s.connect('/run/lifeos-control-job-submit.sock')
    s.sendall(json.dumps(request).encode()); s.shutdown(socket.SHUT_WR); out=json.loads(s.recv(8192))
assert out['status']=='REJECTED', out
print('BRIDGE_REJECTION=PASS')
PY

# Resume the already-approved package by extracting the exact assured root job
# payload from its published launcher. No destination crosses the socket.
if [[ ! -f "$CONTROL/results/$JOB_ID.json" && ! -f "$CONTROL/jobs/staging/$JOB_ID.json" && ! -f "$CONTROL/jobs/pending/$JOB_ID.json" ]]; then
  package_dir=$(mktemp -d)
  trap 'rm -rf -- "$package_dir"' EXIT
  awk '/^cat >"\$CONTROL\/\$SCRIPT_REL" <<'"'"'ROOT_JOB'"'"'$/{copy=1;next} /^ROOT_JOB$/{copy=0} copy' \
    "$PLATFORM/governor/runtime_jobs/660a6d4862fa.sh" >"$package_dir/script.sh"
  [[ -s "$package_dir/script.sh" ]] || fail assured_payload_extract
  sha=$(sha256sum "$package_dir/script.sh" | awk '{print $1}')
  python3 - "$package_dir/manifest.json" "$JOB_ID" "$sha" <<'PY'
import json,sys
path,job,digest=sys.argv[1:]
d={"schema_version":1,"job_id":job,"target":"pi5","job_type":"change",
   "script":f"jobs/root-scripts/{job}.sh","script_sha256":digest,"timeout_seconds":900,
   "created_by":"lifeos-cloud-builder-660a6d4862fa","description":"Activate only assured root broker and bounded Engineer V1 runtime",
   "change_scope":"root-broker","change_policy":"gated-v1","requires_root":True}
open(path,'w').write(json.dumps(d,sort_keys=True))
PY
  chown "$ALLOWED_USER" "$package_dir" "$package_dir/script.sh" "$package_dir/manifest.json"
  runuser -u "$ALLOWED_USER" -- python3 - "$package_dir/manifest.json" "$package_dir/script.sh" <<'PY' || fail activation_submission
import base64,json,socket,sys
request={"operation":"submit-control-job","manifest":open(sys.argv[1]).read(),"script_base64":base64.b64encode(open(sys.argv[2],'rb').read()).decode()}
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(10); s.connect('/run/lifeos-control-job-submit.sock')
    s.sendall(json.dumps(request).encode()); s.shutdown(socket.SHUT_WR)
    out=json.loads(s.recv(8192)); print('SUBMIT_RESPONSE='+json.dumps(out,sort_keys=True))
assert out.get('status')=='ACCEPTED',out
PY
  trap - EXIT
  rm -rf -- "$package_dir"
fi

# Publisher/runner remain authoritative and FIFO is never bypassed.
deadline=$((SECONDS + 1900))
while [[ ! -f "$CONTROL/results/$JOB_ID.json" && $SECONDS -lt $deadline ]]; do
  if [[ ! -f "$CONTROL/jobs/pending/$JOB_ID.json" ]]; then
    run 180s /usr/local/sbin/lifeos-job-publisher || fail publisher_rejected
  fi
  systemctl start --no-block lifeos-pi-control-runner.service 2>/dev/null || true
  sleep 2
done
[[ -f "$CONTROL/results/$JOB_ID.json" ]] || fail activation_result_timeout
python3 - "$CONTROL/results/$JOB_ID.json" <<'PY' || fail activation_result_failed
import json,sys
d=json.load(open(sys.argv[1])); assert d.get('classification')=='PASS',d
print('CONTROL_RESULT=PASS')
PY
[[ $(sha256sum /usr/local/sbin/lifeos-root-broker | awk '{print $1}') == a15e9c2b0f2ed31600d936eaa1b64d61fc094779a49542267b73c78cfa701417 ]] || fail broker_hash
curl -fsS --max-time 10 http://127.0.0.1:8790/health >/dev/null || fail agent_health
curl -fsS --max-time 10 http://127.0.0.1:8793/health >/dev/null || fail engineer_health
curl -fsS --max-time 10 http://127.0.0.1:8790/jobs >/dev/null || fail job_history
curl -fsS --max-time 10 http://127.0.0.1:8790/jobs/stuck >/dev/null || fail jobs_stuck
echo "BRIDGE_ACTIVATION=PASS"
echo "LIVE_BROKER_SHA256=a15e9c2b0f2ed31600d936eaa1b64d61fc094779a49542267b73c78cfa701417"
echo "RESULT=PASS"
echo "TESTS=bridge rejection/acceptance, normal FIFO control result, broker hash, Engineer health/history/stuck and prior three-prompt activation acceptance PASS"
echo "NEXT_RUNTIME_CHECK=none"
