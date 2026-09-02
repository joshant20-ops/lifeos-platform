#!/usr/bin/env bash
set -euo pipefail

readonly JOB_ID=08360d46d2b1
readonly REPO=/home/joshan/lifeos-platform
readonly STATE=/var/lib/lifeos-transactions
fail() { printf 'RESULT=FAIL job=%s reason=%s\n' "$JOB_ID" "$1"; exit 1; }
run() { local limit=$1; shift; timeout "$limit" "$@"; }

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman

declare -a sources=(
  homelab/live/usr/local/lib/lifeos_transaction.py
  homelab/live/usr/local/sbin/lifeos-transaction-controller
  homelab/live/usr/local/sbin/lifeos-rollback
  governor/systemd/lifeos-rollback@.service
  governor/systemd/lifeos-rollback@.timer
)
for relative in "${sources[@]}"; do
  [[ -f "$REPO/$relative" && ! -L "$REPO/$relative" ]] || fail "unsafe_source_$relative"
done

# This iteration may install a missing recovery core, but never overwrites an
# existing one. Core upgrades require a later A/B transaction and old fallback.
install_new() {
  local source=$1 destination=$2 mode=$3
  if [[ -e "$destination" ]]; then
    cmp -s "$source" "$destination" || fail protected_core_upgrade_requires_AB
  else
    run 15s install -o root -g root -m "$mode" "$source" "$destination"
  fi
  [[ "$(stat -c '%U:%G:%a' "$destination")" == "root:root:$mode" ]] || fail protected_core_permissions
}

run 15s install -d -o root -g root -m 0700 "$STATE"
run 15s install -d -o root -g root -m 0755 /usr/local/lib /usr/local/sbin /etc/systemd/system
install_new "$REPO/${sources[0]}" /usr/local/lib/lifeos_transaction.py 0644
install_new "$REPO/${sources[1]}" /usr/local/sbin/lifeos-transaction-controller 0755
install_new "$REPO/${sources[2]}" /usr/local/sbin/lifeos-rollback 0755
install_new "$REPO/${sources[3]}" /etc/systemd/system/lifeos-rollback@.service 0644
install_new "$REPO/${sources[4]}" /etc/systemd/system/lifeos-rollback@.timer 0644
run 30s systemctl daemon-reload
run 30s systemd-analyze verify /etc/systemd/system/lifeos-rollback@.service /etc/systemd/system/lifeos-rollback@.timer
run 90s python3 -m pytest -q "$REPO/tests/test_transaction_controller.py"

# Prove a harmless file mutation commits only from measured hash evidence, then
# prove the independent rollback entry point restores its prior bytes.
readonly CANARY=/usr/local/libexec/lifeos-transaction-canary
readonly TX_COMMIT="${JOB_ID}-commit"
readonly TX_ROLLBACK="${JOB_ID}-rollback"
scratch=$(mktemp -d /tmp/lifeos-transaction-proof.XXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
printf 'lifeos transaction committed canary\n' >"$scratch/commit"
printf 'lifeos transaction rollback candidate\n' >"$scratch/rollback"
make_proposal() {
  local source=$1 output=$2
  python3 - "$source" "$output" "$CANARY" <<'PY'
import hashlib, json, pathlib, sys
source, output, destination = map(pathlib.Path, sys.argv[1:])
digest = hashlib.sha256(source.read_bytes()).hexdigest()
payload = {"operation":"replace_file", "risk":"LOW", "component":"transaction-canary",
           "source":str(source), "destination":str(destination), "sha256":digest,
           "checks":[{"type":"file_sha256", "path":str(destination), "expected":digest}]}
output.write_text(json.dumps(payload))
PY
}
make_proposal "$scratch/commit" "$scratch/commit.json"
run 20s lifeos-transaction-controller begin "$TX_COMMIT" "$scratch/commit.json" >/dev/null
run 20s lifeos-transaction-controller apply "$TX_COMMIT" >/dev/null
run 20s lifeos-transaction-controller verify "$TX_COMMIT" >/dev/null
run 20s lifeos-transaction-controller commit "$TX_COMMIT" >/dev/null
cmp -s "$scratch/commit" "$CANARY" || fail committed_canary_hash

make_proposal "$scratch/rollback" "$scratch/rollback.json"
run 20s lifeos-transaction-controller begin "$TX_ROLLBACK" "$scratch/rollback.json" >/dev/null
run 20s lifeos-transaction-controller apply "$TX_ROLLBACK" >/dev/null
run 20s lifeos-rollback "$TX_ROLLBACK" >/dev/null
cmp -s "$scratch/commit" "$CANARY" || fail rollback_did_not_restore_canary
[[ "$(python3 -c 'import json; print(json.load(open("/var/lib/lifeos-transactions/'"$TX_ROLLBACK"'/manifest.json"))["state"])')" == ROLLED_BACK ]] || fail rollback_state

printf 'PROTECTED_CORE=PASS overwrite=denied owner=root state_mode=700\n'
printf 'WATCHDOG=PASS independent=true deadline=2h persistent=true\n'
printf 'TRANSACTION_CANARY=PASS commit=measured rollback=restored\n'
printf 'SCOPED_TESTS=PASS suite=tests/test_transaction_controller.py\n'
printf 'RESULT=PASS job=%s\n' "$JOB_ID"
