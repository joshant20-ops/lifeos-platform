#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL=/home/joshan/lifeos-pi-control
readonly PUBLISHER=/usr/local/sbin/lifeos-job-publisher
readonly CANONICAL="$PLATFORM/homelab/live/usr/local/sbin/lifeos-job-publisher"
readonly EXPECTED_SHA=c17e686746a932d87996eb9cb375f5076603b5a618250853f4f007d81db284bc
readonly JOB_ID=activate-engineer-v1-660a6d4862fa
readonly CLEAN_PATH=/usr/bin:/bin

result() {
  echo "RESULT=$1"
  echo "TESTS=$2"
  echo "NEXT_RUNTIME_CHECK=$3"
}
fail() { echo "FAIL=$1"; result RETRY "publisher identity/connectivity/resume check failed" "inspect FAIL=$1"; exit 1; }
run() { timeout --signal=TERM --kill-after=10s "$@"; }
sha() { sha256sum "$1" | awk '{print $1}'; }

[[ -d "$PLATFORM/.git" && -d "$CONTROL/.git" ]] || fail canonical_repository_missing

echo 'INSPECTION=lifeos-job-publisher.service'
systemctl cat lifeos-job-publisher.service 2>&1 || true
systemctl show lifeos-job-publisher.service -p User -p Group -p ExecStart --no-pager 2>&1 || true
stat -c 'PUBLISHER_STAT=owner=%U group=%G mode=%a path=%n' "$PUBLISHER" || fail live_publisher_missing
stat -c 'CONTROL_REPO_STAT=owner=%U group=%G mode=%a path=%n' "$CONTROL" || fail control_repo_missing
echo "CANONICAL_PUBLISHER_SHA256=$(sha "$CANONICAL")"
echo "LIVE_PUBLISHER_SHA256=$(sha "$PUBLISHER")"
sed -n '45,75p' "$PLATFORM/homelab/live/usr/local/sbin/lifeos-github-sync" | sed -E 's/(KEY|TOKEN|SECRET|PASSWORD)=[^ ]+/<redacted>/Ig'
systemctl cat lifeos-pi-control-runner.service 2>&1 || true
systemctl show lifeos-pi-control-runner.service -p User -p Group -p ExecStart --no-pager 2>&1 || true

[[ $(sha "$CANONICAL") == "$EXPECTED_SHA" ]] || fail canonical_publisher_checksum
unit_user=$(systemctl show lifeos-job-publisher.service -p User --value 2>/dev/null || true)
if [[ -z "$unit_user" || "$unit_user" == root ]]; then
  contract=root
elif [[ "$unit_user" == joshan ]]; then
  contract=joshan
else
  echo "FAIL=publisher_execution_identity"
  echo "EFFECTIVE_UNIT_USER=$unit_user"
  result RETRY "publisher service has an unsupported execution identity" "correct the service identity without weakening publisher checks"
  exit 1
fi
echo "PUBLISHER_EXECUTION_CONTRACT=$contract"

# Never mistake an unprivileged diagnostic invocation for the service contract.
if [[ "$contract" == root && $(id -u) -ne 0 ]]; then
  echo "IDENTITY_CHECK=publisher requires root control context; runuser probe intentionally not attempted"
  echo "HUMAN_ACTION_REQUIRED=sudo $PLATFORM/governor/runtime_jobs/525389a49348.sh"
  result BLOCKED "read-only inspection passed; root publisher identity and protected activation remain" "sudo $PLATFORM/governor/runtime_jobs/525389a49348.sh"
  exit 20
fi
if [[ "$contract" == joshan && $(id -un) != joshan ]]; then
  fail publisher_execution_identity
fi

git_context() {
  if [[ "$contract" == root ]]; then
    runuser -u joshan -- env -i HOME=/home/joshan PATH="$CLEAN_PATH" LANG=C.UTF-8 "$@"
  else
    env -i HOME=/home/joshan PATH="$CLEAN_PATH" LANG=C.UTF-8 "$@"
  fi
}

# Connectivity is checked with exactly the identity and clean environment used by Git.
if ! git_context getent ahosts github.com >/dev/null; then
  echo 'FAIL=dns_resolution'
  result RETRY "publisher identity valid; github.com DNS resolution failed" "repeat DNS probe in the same publisher Git context"
  exit 1
fi
echo 'DNS_RESOLUTION=PASS'
lsout=$(mktemp); trap 'rm -f -- "$lsout"' EXIT
if ! git_context /usr/bin/git -C "$CONTROL" ls-remote origin refs/heads/main >"$lsout" 2>&1; then
  if grep -Eqi 'Permission denied|publickey|Authentication failed|access rights' "$lsout"; then class=ssh_authentication; else class=git_remote; fi
  echo "FAIL=$class"
  sed -E 's#(token|password|secret|key)[=:][^ ]+#\1=<redacted>#Ig' "$lsout"
  result RETRY "DNS passed; Git remote check failed closed as $class" "repair $class in the fixed joshan Git context"
  exit 1
fi
echo 'GIT_LS_REMOTE_ORIGIN_MAIN=PASS'
rm -f -- "$lsout"; trap - EXIT

if [[ $(sha "$PUBLISHER") != "$EXPECTED_SHA" ]]; then
  echo "HUMAN_ACTION_REQUIRED=activate canonical publisher only through an existing checksum-pinned protected activation path; expected sha256 $EXPECTED_SHA"
  result BLOCKED "identity and connectivity passed; live publisher differs from canonical" "activate publisher sha256 $EXPECTED_SHA, then rerun this launcher"
  exit 20
fi
echo 'PUBLISHER_ACTIVATION=already-active'

# The accepted job must never be recreated. Continue only from its existing state.
matches=0
for p in "$CONTROL/jobs/staging/$JOB_ID.json" "$CONTROL/jobs/pending/$JOB_ID.json" "$CONTROL/jobs/archive/$JOB_ID.json" "$CONTROL/results/$JOB_ID.json"; do
  [[ -f "$p" ]] && { echo "EXISTING_JOB_ARTIFACT=$p"; matches=$((matches+1)); }
done
(( matches > 0 )) || fail existing_accepted_job_missing

deadline=$((SECONDS + 1900))
while [[ ! -f "$CONTROL/results/$JOB_ID.json" && $SECONDS -lt $deadline ]]; do
  if [[ -f "$CONTROL/jobs/staging/$JOB_ID.json" ]]; then
    run 180s "$PUBLISHER" || fail publisher_failed_closed
  fi
  systemctl start --no-block lifeos-pi-control-runner.service || fail control_runner_start
  sleep 2
done
[[ -f "$CONTROL/results/$JOB_ID.json" ]] || fail activation_result_timeout
python3 - "$CONTROL/results/$JOB_ID.json" <<'PY' || fail activation_result_failed
import json,sys
d=json.load(open(sys.argv[1])); assert d.get('classification') == 'PASS', d
print('CONTROL_RESULT=PASS')
PY
curl -fsS --max-time 10 http://127.0.0.1:8790/health >/dev/null || fail agent_health
curl -fsS --max-time 10 http://127.0.0.1:8793/health >/dev/null || fail engineer_health
curl -fsS --max-time 10 http://127.0.0.1:8790/jobs >/dev/null || fail job_history
curl -fsS --max-time 10 http://127.0.0.1:8790/jobs/stuck >/dev/null || fail jobs_stuck
echo 'RESUMED_CHAIN=PASS'
result PASS "publisher identity/DNS/Git, existing control result, both services, history and stuck checks PASS" none
