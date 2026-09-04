#!/usr/bin/env bash
set -Eeuo pipefail

# LifeOS control-plane Git/runtime ownership migration.
# Run as joshan on the Pi 5. The script uses sudo only for systemd and
# root-owned binary/file preservation. It is fail-closed and preserves runtime
# queue/results/state before any destructive checkout operation.

readonly CONTROL=/home/joshan/lifeos-pi-control
readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL_OWNERSHIP_COMMIT=fae946238b9c32da7c15fd8e271008330a3a4196
readonly SAFE_PLATFORM_COMMIT=f774fb6ef4c9bef431803d60ed4e0abb6f0ecf2a
readonly ACTIVATION_ID=activate-engineer-v1-660a6d4862fa
readonly ACTIVATION_MANIFEST_REL="jobs/pending/${ACTIVATION_ID}.json"
readonly ACTIVATION_SCRIPT_REL="jobs/root-scripts/${ACTIVATION_ID}.sh"
readonly ACTIVATION_SCRIPT_SHA=bd24600e7abfda6e18bbd725fe0f9814a575795e8748b38951c2bb6eb85c6878
readonly DEPLOY_ID=engineer-v1-660a6d4862fa
readonly RUNNER=/usr/local/sbin/lifeos-pi-control-runner
readonly PUBLISHER=/usr/local/sbin/lifeos-job-publisher
readonly PAUSE=/home/joshan/.local/state/lifeos-pi-control/paused_job
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly BACKUP_ROOT="/home/joshan/lifeos-control-runtime-backups/${STAMP}"
readonly RUNTIME_TAR="${BACKUP_ROOT}/runtime.tar"
readonly RUNTIME_SUMS="${BACKUP_ROOT}/runtime.sha256"
readonly STATUS_LOG="${BACKUP_ROOT}/migration-status.txt"

RUNTIME_PATHS=(
  jobs/staging
  jobs/staged
  jobs/pending
  jobs/archive
  jobs/scripts
  jobs/change-scripts
  jobs/root-scripts
  results
  state
)

OLD_CONTROL_HEAD=""
MUTATION_STARTED=0
MIGRATION_VERIFIED=0
BINARIES_DEPLOYED=0
ACTIVATION_PENDING=0
ACTIVATION_ALREADY_COMPLETE=0
HELD_PENDING=0
SUBMIT_SOCKET_WAS_ACTIVE=0
DISCOVERED_UNITS=()
ACTIVE_UNITS=()

stage() { printf '\n===== STAGE %s — %s =====\n' "$1" "$2"; }
pass() { printf 'STAGE_%s=PASS\n' "$1"; }
fail() {
  local s="$1"; shift
  printf 'STAGE_%s=FAIL\n' "$s" >&2
  printf 'FAIL_REASON=%s\n' "$*" >&2
  diagnostics >&2 || true
  exit 1
}
sha() { sha256sum "$1" | awk '{print $1}'; }

is_runtime_path() {
  local p="$1" root
  p="${p#./}"
  for root in "${RUNTIME_PATHS[@]}"; do
    [[ "$p" == "$root" || "$p" == "$root/"* ]] && return 0
  done
  return 1
}

diagnostics() {
  echo '--- diagnostics ---'
  echo "host=$(hostname 2>/dev/null || true)"
  echo "user=$(id -un 2>/dev/null || true)"
  echo "backup=${BACKUP_ROOT}"
  [[ -d "$CONTROL/.git" ]] && {
    echo "control_head=$(git -C "$CONTROL" rev-parse HEAD 2>/dev/null || true)"
    echo "control_branch=$(git -C "$CONTROL" branch --show-current 2>/dev/null || true)"
    echo 'control_status:'
    git -C "$CONTROL" status --short 2>/dev/null | head -80 || true
  }
  [[ -d "$PLATFORM/.git" ]] && {
    echo "platform_head=$(git -C "$PLATFORM" rev-parse HEAD 2>/dev/null || true)"
    echo "platform_branch=$(git -C "$PLATFORM" branch --show-current 2>/dev/null || true)"
    echo 'platform_status:'
    git -C "$PLATFORM" status --short 2>/dev/null | head -40 || true
  }
  echo "activation_pending=$([[ -f "$CONTROL/$ACTIVATION_MANIFEST_REL" ]] && echo yes || echo no)"
  echo "activation_archive=$([[ -f "$CONTROL/jobs/archive/$ACTIVATION_ID.json" ]] && echo yes || echo no)"
  echo "activation_result=$([[ -f "$CONTROL/results/$ACTIVATION_ID.json" ]] && echo yes || echo no)"
  [[ -f "$PAUSE" ]] && echo "paused_job=$(cat "$PAUSE" 2>/dev/null || true)"
  systemctl is-active lifeos-control-job-submit.socket 2>/dev/null || true
  pgrep -af 'lifeos-(job-publisher|pi-control-runner)' 2>/dev/null || true
  echo '--- end diagnostics ---'
}

restore_services() {
  set +e
  local unit
  for unit in "${ACTIVE_UNITS[@]}"; do
    sudo systemctl start "$unit" >/dev/null 2>&1 || true
  done
  if (( SUBMIT_SOCKET_WAS_ACTIVE )); then
    sudo systemctl start lifeos-control-job-submit.socket >/dev/null 2>&1 || true
  fi
}

restore_held_pending() {
  set +e
  if (( HELD_PENDING )) && [[ -d "$BACKUP_ROOT/held-pending" ]]; then
    mkdir -p "$CONTROL/jobs/pending"
    find "$BACKUP_ROOT/held-pending" -maxdepth 1 -type f -name '*.json' -print0 2>/dev/null |
      while IFS= read -r -d '' f; do mv -n "$f" "$CONTROL/jobs/pending/" || true; done
  fi
}

rollback_migration() {
  set +e
  (( MUTATION_STARTED )) || return 0
  (( MIGRATION_VERIFIED )) && return 0
  echo 'ROLLBACK=START'
  if [[ -n "$OLD_CONTROL_HEAD" && -d "$CONTROL/.git" ]]; then
    sudo rm -rf "${RUNTIME_PATHS[@]/#/$CONTROL/}" 2>/dev/null || true
    git -C "$CONTROL" reset --hard "$OLD_CONTROL_HEAD" >/dev/null 2>&1 || true
  fi
  if [[ -f "$RUNTIME_TAR" ]]; then
    sudo tar -C "$CONTROL" --acls --xattrs --numeric-owner -xpf "$RUNTIME_TAR" >/dev/null 2>&1 || true
  fi
  echo 'ROLLBACK=ATTEMPTED'
}

on_exit() {
  local rc=$?
  restore_held_pending
  if (( rc != 0 )); then rollback_migration; fi
  restore_services
  if (( rc != 0 )); then
    echo "FINAL_STATUS=FAIL"
    echo "BACKUP=$BACKUP_ROOT"
  fi
  exit "$rc"
}
trap on_exit EXIT

write_runtime_sums() {
  sudo bash -c '
    set -Eeuo pipefail
    cd "$1"
    shift
    for root in "$@"; do
      [[ -e "$root" ]] || continue
      find "$root" -type f -print0
    done | sort -z | xargs -0 -r sha256sum
  ' bash "$CONTROL" "${RUNTIME_PATHS[@]}" > "$RUNTIME_SUMS"
}

verify_runtime_sums() {
  [[ -f "$RUNTIME_SUMS" ]] || return 1
  (cd "$CONTROL" && sudo sha256sum -c "$RUNTIME_SUMS")
}

stage 1 'PREFLIGHT'
[[ "$(id -un)" == joshan ]] || fail 1 'must run as user joshan'
for cmd in git tar sha256sum python3 flock sudo systemctl install timeout; do
  command -v "$cmd" >/dev/null 2>&1 || fail 1 "missing required command: $cmd"
done
sudo -v || fail 1 'sudo authentication failed'
[[ -d "$CONTROL/.git" ]] || fail 1 "control repository missing: $CONTROL"
[[ -d "$PLATFORM/.git" ]] || fail 1 "canonical platform checkout missing: $PLATFORM"
[[ "$(git -C "$CONTROL" branch --show-current)" == main ]] || fail 1 'control checkout must be on main'
[[ "$(git -C "$PLATFORM" branch --show-current)" == main ]] || fail 1 'platform checkout must be on main'
[[ -f /etc/lifeos-control/identity.json ]] || fail 1 'control identity missing'
OLD_CONTROL_HEAD="$(git -C "$CONTROL" rev-parse HEAD)"
mkdir -p "$BACKUP_ROOT"
printf 'started=%s\nold_control_head=%s\n' "$(date -Iseconds)" "$OLD_CONTROL_HEAD" > "$STATUS_LOG"
pass 1

stage 2 'STATIC REPOSITORY GATES'
# Platform must be clean outside generated/untracked material before its main ref is advanced.
[[ -z "$(git -C "$PLATFORM" status --porcelain --untracked-files=no)" ]] || fail 2 'platform tracked working tree is dirty'
git -C "$PLATFORM" fetch origin main || fail 2 'platform fetch failed'
git -C "$PLATFORM" merge-base --is-ancestor "$SAFE_PLATFORM_COMMIT" origin/main || fail 2 'safe runner/publisher commit is not in origin/main'
git -C "$PLATFORM" merge --ff-only origin/main || fail 2 'platform main cannot fast-forward'

# Control static changes are forbidden; runtime-owned drift is expected and separately preserved.
while IFS= read -r p; do
  [[ -z "$p" ]] && continue
  is_runtime_path "$p" || fail 2 "unexpected tracked control change outside runtime ownership: $p"
done < <({ git -C "$CONTROL" diff --name-only; git -C "$CONTROL" diff --cached --name-only; } | sort -u)
while IFS= read -r p; do
  [[ -z "$p" ]] && continue
  is_runtime_path "$p" || fail 2 "unexpected untracked control file outside runtime ownership: $p"
done < <(git -C "$CONTROL" ls-files --others --exclude-standard)

git -C "$CONTROL" fetch origin main || fail 2 'control fetch failed'
git -C "$CONTROL" merge-base --is-ancestor "$CONTROL_OWNERSHIP_COMMIT" origin/main || fail 2 'runtime ownership migration commit is not in control origin/main'
remote_runtime="$(git -C "$CONTROL" ls-tree -r --name-only origin/main -- "${RUNTIME_PATHS[@]}")"
[[ -z "$remote_runtime" ]] || { printf '%s\n' "$remote_runtime"; fail 2 'control origin/main still tracks runtime-owned paths'; }
pass 2

stage 3 'ACTIVATION AND REPLAY GATES'
manifest="$CONTROL/$ACTIVATION_MANIFEST_REL"
script="$CONTROL/$ACTIVATION_SCRIPT_REL"
result="$CONTROL/results/$ACTIVATION_ID.json"
archive="$CONTROL/jobs/archive/$ACTIVATION_ID.json"
if [[ -f "$result" || -f "$archive" ]]; then
  [[ -f "$result" && -f "$archive" && ! -f "$manifest" ]] || fail 3 'activation has conflicting pending/archive/result state'
  ACTIVATION_ALREADY_COMPLETE=1
  echo 'ACTIVATION_STATE=already-complete'
elif [[ -f "$manifest" ]]; then
  [[ -f "$script" ]] || fail 3 'accepted activation script missing'
  [[ "$(sha "$script")" == "$ACTIVATION_SCRIPT_SHA" ]] || fail 3 'accepted activation script checksum mismatch'
  python3 - "$manifest" "$ACTIVATION_SCRIPT_REL" "$ACTIVATION_SCRIPT_SHA" <<'PY' || fail 3 'activation manifest validation failed'
import json,sys
p,rel,want=sys.argv[1:]
d=json.load(open(p))
assert d['job_id']=='activate-engineer-v1-660a6d4862fa'
assert d['job_type']=='change' and d['change_scope']=='root-broker' and d['requires_root'] is True
assert d['change_policy']=='gated-v1' and d['script']==rel and d['script_sha256']==want
assert d['timeout_seconds']==900
PY
  [[ ! -e "/var/lib/lifeos-control/engineer-deploy-approvals/$DEPLOY_ID.json" ]] || fail 3 'activation approval replay artifact already exists while job is pending'
  [[ ! -e "/var/lib/lifeos-control/engineer-deploy-audit/$DEPLOY_ID.json" ]] || fail 3 'activation audit replay artifact already exists while job is pending'
  ACTIVATION_PENDING=1
  echo 'ACTIVATION_STATE=pending-and-valid'
else
  fail 3 'accepted activation is neither pending nor already complete'
fi
pass 3

stage 4 'QUIESCE CONTROL WRITERS'
if systemctl is-active --quiet lifeos-control-job-submit.socket; then
  SUBMIT_SOCKET_WAS_ACTIVE=1
  sudo systemctl stop lifeos-control-job-submit.socket || fail 4 'could not stop control submission socket'
fi
# Discover any systemd unit that launches the publisher or runner. Stop only units
# that are currently active, and restore exactly those at exit.
while IFS= read -r unit; do
  [[ -n "$unit" ]] || continue
  if systemctl cat "$unit" 2>/dev/null | grep -Eq 'lifeos-job-publisher|lifeos-pi-control-runner'; then
    DISCOVERED_UNITS+=("$unit")
    if systemctl is-active --quiet "$unit"; then ACTIVE_UNITS+=("$unit"); fi
  fi
done < <(systemctl list-unit-files --type=service --type=timer --no-legend 2>/dev/null | awk '{print $1}')
for unit in "${ACTIVE_UNITS[@]}"; do sudo systemctl stop "$unit" || fail 4 "could not stop $unit"; done
mkdir -p "$CONTROL/state" /home/joshan/.local/state/lifeos-pi-control
exec 8>"$CONTROL/state/publisher.lock"
flock -n 8 || fail 4 'publisher lock is held by a non-quiesced process'
exec 9>/home/joshan/.local/state/lifeos-pi-control/runner.lock
flock -n 9 || fail 4 'runner lock is held by a non-quiesced process'
pgrep -af 'lifeos-(job-publisher|pi-control-runner)' && fail 4 'control writer process remains active after quiesce' || true
pass 4

stage 5 'PRESERVE RUNTIME STATE'
existing=()
for root in "${RUNTIME_PATHS[@]}"; do [[ -e "$CONTROL/$root" ]] && existing+=("$root"); done
((${#existing[@]} > 0)) || fail 5 'no runtime paths found to preserve'
sudo tar -C "$CONTROL" --acls --xattrs --numeric-owner -cpf "$RUNTIME_TAR" "${existing[@]}" || fail 5 'runtime tar backup failed'
sudo chown joshan:joshan "$RUNTIME_TAR"
write_runtime_sums || fail 5 'runtime checksum inventory failed'
[[ -s "$RUNTIME_TAR" ]] || fail 5 'runtime backup is empty'
sha "$RUNTIME_TAR" > "$BACKUP_ROOT/runtime.tar.sha256"
cp -a "$manifest" "$BACKUP_ROOT/activation-manifest.json" 2>/dev/null || true
cp -a "$script" "$BACKUP_ROOT/activation-script.sh" 2>/dev/null || true
sync
printf 'runtime_files=%s\nruntime_tar_sha=%s\n' "$(wc -l < "$RUNTIME_SUMS")" "$(cat "$BACKUP_ROOT/runtime.tar.sha256")" >> "$STATUS_LOG"
pass 5

stage 6 'MIGRATE CONTROL REPOSITORY OWNERSHIP'
MUTATION_STARTED=1
# Remove runtime bytes only after the validated external backup exists. Restore
# the old tracked snapshot so Git can perform a clean fast-forward that deletes
# runtime paths from the index, then restore the live bytes as ignored runtime state.
for root in "${RUNTIME_PATHS[@]}"; do sudo rm -rf "$CONTROL/$root"; done
tracked_old=()
for root in "${RUNTIME_PATHS[@]}"; do
  if git -C "$CONTROL" ls-tree -r --name-only HEAD -- "$root" | grep -q .; then tracked_old+=("$root"); fi
done
if ((${#tracked_old[@]})); then
  git -C "$CONTROL" restore --source=HEAD --staged --worktree -- "${tracked_old[@]}" || fail 6 'could not normalize old tracked runtime snapshot'
fi
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 6 'control tree not clean after runtime normalization'
git -C "$CONTROL" merge-base --is-ancestor HEAD origin/main || fail 6 'control local HEAD is not a fast-forward ancestor of origin/main'
git -C "$CONTROL" merge --ff-only origin/main || fail 6 'control ownership fast-forward failed'
[[ -z "$(git -C "$CONTROL" ls-files -- "${RUNTIME_PATHS[@]}")" ]] || fail 6 'runtime paths remain tracked after migration'
sudo tar -C "$CONTROL" --acls --xattrs --numeric-owner -xpf "$RUNTIME_TAR" || fail 6 'runtime restore failed'
verify_runtime_sums || fail 6 'restored runtime bytes do not match backup checksums'
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 6 'static control definitions dirty after runtime restore'
MIGRATION_VERIFIED=1
printf 'new_control_head=%s\n' "$(git -C "$CONTROL" rev-parse HEAD)" >> "$STATUS_LOG"
pass 6

stage 7 'DEPLOY SAFE PUBLISHER AND RUNNER'
mkdir -p "$BACKUP_ROOT/bin"
for live in "$PUBLISHER" "$RUNNER"; do
  [[ -f "$live" ]] && sudo cp -a "$live" "$BACKUP_ROOT/bin/$(basename "$live").pre-migration" || true
done
pub_tmp="$(mktemp)"; run_tmp="$(mktemp)"
trap 'rm -f "$pub_tmp" "$run_tmp" 2>/dev/null || true; on_exit' EXIT
git -C "$PLATFORM" show "$SAFE_PLATFORM_COMMIT:homelab/live/usr/local/sbin/lifeos-job-publisher" > "$pub_tmp" || fail 7 'cannot extract safe publisher from pinned platform commit'
git -C "$PLATFORM" show "$SAFE_PLATFORM_COMMIT:homelab/live/usr/local/sbin/lifeos-pi-control-runner" > "$run_tmp" || fail 7 'cannot extract safe runner from pinned platform commit'
python3 -m py_compile "$pub_tmp" "$run_tmp" || fail 7 'safe control binaries fail Python compilation'
grep -Fq '+refs/heads/main:refs/remotes/origin/main' "$pub_tmp" || fail 7 'publisher fixed-fetch marker missing'
grep -Fq 'jobs/staged' "$pub_tmp" || fail 7 'publisher legacy runtime guard missing'
grep -Fq '"persistence": "local-runtime"' "$run_tmp" || fail 7 'runner local-runtime persistence marker missing'
if grep -Eq 'git\(("|\x27)(add|push|rebase)' "$run_tmp"; then fail 7 'runner still contains runtime Git publication'; fi
sudo install -o root -g root -m 0755 "$pub_tmp" "$PUBLISHER" || fail 7 'publisher install failed'
sudo install -o root -g root -m 0755 "$run_tmp" "$RUNNER" || fail 7 'runner install failed'
[[ "$(sha "$PUBLISHER")" == "$(sha "$pub_tmp")" ]] || fail 7 'publisher post-install checksum mismatch'
[[ "$(sha "$RUNNER")" == "$(sha "$run_tmp")" ]] || fail 7 'runner post-install checksum mismatch'
BINARIES_DEPLOYED=1
rm -f "$pub_tmp" "$run_tmp"
trap on_exit EXIT
pass 7

stage 8 'POST-MIGRATION CONTROL GATES'
[[ -z "$(git -C "$CONTROL" ls-files -- "${RUNTIME_PATHS[@]}")" ]] || fail 8 'runtime ownership regression after binary deployment'
for expected in jobs/pending/ results/ state/; do grep -Fxq "$expected" "$CONTROL/.gitignore" || fail 8 "control gitignore missing $expected"; done
if (( ACTIVATION_PENDING )); then
  [[ -f "$manifest" && -f "$script" ]] || fail 8 'activation pair disappeared during migration'
  [[ "$(sha "$script")" == "$ACTIVATION_SCRIPT_SHA" ]] || fail 8 'activation script changed during migration'
  [[ "$(sha "$manifest")" == "$(sha "$BACKUP_ROOT/activation-manifest.json")" ]] || fail 8 'activation manifest changed during migration'
fi
# Direct pre-change gates: do not consume the one-shot activation if its known
# prerequisites are currently unhealthy.
/usr/local/sbin/lifeos-ansible-adopt --status >/tmp/lifeos-migration-v3-status.$$ 2>&1 || {
  tail -80 /tmp/lifeos-migration-v3-status.$$ || true; rm -f /tmp/lifeos-migration-v3-status.$$; fail 8 'V3 baseline is not healthy'; }
rm -f /tmp/lifeos-migration-v3-status.$$
python3 - <<'PY' || fail 8 'critical Docker service baseline failed'
import subprocess
running=set(subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines())
required={'homeassistant','lifeos-energy','predbat','vaultwarden','uptime-kuma','prometheus','autoheal','watchtower'}
missing=sorted(required-running)
if missing:
    print('MISSING_CRITICAL_CONTAINERS='+','.join(missing)); raise SystemExit(1)
print('CRITICAL_CONTAINERS=PASS')
PY
pass 8

stage 9 'EXECUTE ACCEPTED ACTIVATION EXACTLY ONCE'
if (( ACTIVATION_ALREADY_COMPLETE )); then
  echo 'ACTIVATION_EXECUTION=SKIP_ALREADY_COMPLETE'
  pass 9
else
  [[ ! -s "$PAUSE" ]] || { echo "PAUSED_JOB=$(cat "$PAUSE")"; fail 9 'runner is paused; refusing to bypass pause semantics'; }
  mkdir -p "$BACKUP_ROOT/held-pending"
  shopt -s nullglob
  for f in "$CONTROL"/jobs/pending/*.json; do
    [[ "$(basename "$f")" == "$ACTIVATION_ID.json" ]] && continue
    mv "$f" "$BACKUP_ROOT/held-pending/"
    HELD_PENDING=1
  done
  shopt -u nullglob
  [[ -f "$manifest" ]] || fail 9 'activation job not present after pending isolation'
  set +e
  "$RUNNER" > "$BACKUP_ROOT/activation-runner.log" 2>&1
  runner_rc=$?
  set -e
  restore_held_pending
  HELD_PENDING=0
  cat "$BACKUP_ROOT/activation-runner.log"
  (( runner_rc == 0 )) || fail 9 "safe runner returned rc=$runner_rc"
  [[ ! -f "$manifest" ]] || fail 9 'activation manifest remains pending after runner success'
  [[ -f "$archive" && -f "$result" ]] || fail 9 'activation archive/result not produced'
  python3 - "$result" <<'PY' || fail 9 'activation result is not PASS'
import json,sys
d=json.load(open(sys.argv[1]))
assert d['job_id']=='activate-engineer-v1-660a6d4862fa'
assert d['classification']=='PASS' and d['exit_code']==0
assert d.get('persistence')=='local-runtime'
print('ACTIVATION_RESULT=PASS')
PY
  pass 9
fi

stage 10 'REGRESSION AND FINAL EVIDENCE'
verify_runtime_sums >/dev/null 2>&1 || {
  # Expected differences after successful activation are confined to pending,
  # archive, results and state. The immutable activation script must still match.
  [[ "$(sha "$CONTROL/$ACTIVATION_SCRIPT_REL")" == "$ACTIVATION_SCRIPT_SHA" ]] || fail 10 'activation script mutated after execution'
  echo 'RUNTIME_CHECKSUM_NOTE=expected queue/result changes after activation'
}
[[ -z "$(git -C "$CONTROL" ls-files -- "${RUNTIME_PATHS[@]}")" ]] || fail 10 'runtime paths became tracked again'
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 10 'control static definitions are dirty'
grep -Fq 'local-runtime' "$RUNNER" || fail 10 'safe runner missing at final gate'
grep -Fq 'jobs/staged' "$PUBLISHER" || fail 10 'safe publisher missing at final gate'
if (( ACTIVATION_PENDING )); then
  [[ -f "$CONTROL/results/$ACTIVATION_ID.json" ]] || fail 10 'activation result absent at final gate'
fi
printf 'completed=%s\nfinal_control_head=%s\nplatform_head=%s\n' \
  "$(date -Iseconds)" "$(git -C "$CONTROL" rev-parse HEAD)" "$(git -C "$PLATFORM" rev-parse HEAD)" >> "$STATUS_LOG"
pass 10

restore_services
SUBMIT_SOCKET_WAS_ACTIVE=0
ACTIVE_UNITS=()
trap - EXIT
echo 'FINAL_STATUS=PASS'
echo "BACKUP=$BACKUP_ROOT"
echo "CONTROL_HEAD=$(git -C "$CONTROL" rev-parse HEAD)"
echo "PLATFORM_HEAD=$(git -C "$PLATFORM" rev-parse HEAD)"
echo "ACTIVATION_RESULT=$([[ -f "$CONTROL/results/$ACTIVATION_ID.json" ]] && python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("classification","UNKNOWN"))' "$CONTROL/results/$ACTIVATION_ID.json" || echo NOT_RUN)"
