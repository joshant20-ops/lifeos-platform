#!/usr/bin/env bash
set -Eeuo pipefail

# Gated live migration for the LifeOS Pi control repository.
# Run as user joshan on the Pi. Runtime queue/results/state are backed up before
# Git ownership changes. The obsolete Engineer activation is quarantined, not
# executed: its assured broker bytes no longer match canonical main.

readonly CONTROL=/home/joshan/lifeos-pi-control
readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL_OWNERSHIP_COMMIT=fae946238b9c32da7c15fd8e271008330a3a4196
readonly SAFE_PLATFORM_COMMIT=f774fb6ef4c9bef431803d60ed4e0abb6f0ecf2a
readonly STALE_ACTIVATION_ID=activate-engineer-v1-660a6d4862fa
readonly STALE_MANIFEST="jobs/pending/${STALE_ACTIVATION_ID}.json"
readonly STALE_SCRIPT="jobs/root-scripts/${STALE_ACTIVATION_ID}.sh"
readonly STALE_SCRIPT_SHA=bd24600e7abfda6e18bbd725fe0f9814a575795e8748b38951c2bb6eb85c6878
readonly RUNNER=/usr/local/sbin/lifeos-pi-control-runner
readonly PUBLISHER=/usr/local/sbin/lifeos-job-publisher
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly BACKUP="/home/joshan/lifeos-control-runtime-backups/${STAMP}"
readonly RUNTIME_TAR="$BACKUP/runtime.tar"
readonly RUNTIME_SUMS="$BACKUP/runtime.sha256"

RUNTIME_PATHS=(
  jobs/staging jobs/staged jobs/pending jobs/archive jobs/scripts
  jobs/change-scripts jobs/root-scripts results state
)

OLD_HEAD=""
MUTATION_STARTED=0
MIGRATION_VERIFIED=0
QUIESCED=0
SAFE_TO_RESTORE_WRITERS=0
SUBMIT_SOCKET_WAS_ACTIVE=0
ACTIVE_UNITS=()

stage(){ printf '\n===== STAGE %s — %s =====\n' "$1" "$2"; }
pass(){ printf 'STAGE_%s=PASS\n' "$1"; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

is_runtime_path(){
  local p="${1#./}" root
  for root in "${RUNTIME_PATHS[@]}"; do
    [[ "$p" == "$root" || "$p" == "$root/"* ]] && return 0
  done
  return 1
}

diagnostics(){
  echo '--- DIAGNOSTICS ---'
  echo "host=$(hostname 2>/dev/null || true)"
  echo "user=$(id -un 2>/dev/null || true)"
  echo "backup=$BACKUP"
  echo "quiesced=$QUIESCED"
  echo "migration_verified=$MIGRATION_VERIFIED"
  echo "safe_to_restore_writers=$SAFE_TO_RESTORE_WRITERS"
  if [[ -d "$CONTROL/.git" ]]; then
    echo "control_head=$(git -C "$CONTROL" rev-parse HEAD 2>/dev/null || true)"
    echo "control_branch=$(git -C "$CONTROL" branch --show-current 2>/dev/null || true)"
    git -C "$CONTROL" status --short 2>/dev/null | head -80 || true
  fi
  if [[ -d "$PLATFORM/.git" ]]; then
    echo "platform_head=$(git -C "$PLATFORM" rev-parse HEAD 2>/dev/null || true)"
    git -C "$PLATFORM" status --short 2>/dev/null | head -40 || true
  fi
  echo "stale_activation_pending=$([[ -f "$CONTROL/$STALE_MANIFEST" ]] && echo yes || echo no)"
  echo "stale_activation_result=$([[ -f "$CONTROL/results/$STALE_ACTIVATION_ID.json" ]] && echo yes || echo no)"
  [[ -f /home/joshan/.local/state/lifeos-pi-control/paused_job ]] && \
    echo "paused_job=$(cat /home/joshan/.local/state/lifeos-pi-control/paused_job 2>/dev/null || true)"
  pgrep -af 'lifeos-(job-publisher|pi-control-runner)' 2>/dev/null || true
  echo '--- END DIAGNOSTICS ---'
}

fail(){
  local s="$1"; shift
  printf 'STAGE_%s=FAIL\nFAIL_REASON=%s\n' "$s" "$*" >&2
  diagnostics >&2 || true
  exit 1
}

restore_services(){
  set +e
  local u
  for u in "${ACTIVE_UNITS[@]}"; do sudo systemctl start "$u" >/dev/null 2>&1 || true; done
  (( SUBMIT_SOCKET_WAS_ACTIVE )) && sudo systemctl start lifeos-control-job-submit.socket >/dev/null 2>&1 || true
}

rollback(){
  set +e
  (( MUTATION_STARTED )) || return 0
  (( MIGRATION_VERIFIED )) && return 0
  echo 'ROLLBACK=START'
  if [[ -n "$OLD_HEAD" && -d "$CONTROL/.git" ]]; then
    for r in "${RUNTIME_PATHS[@]}"; do sudo rm -rf "$CONTROL/$r"; done
    git -C "$CONTROL" reset --hard "$OLD_HEAD" >/dev/null 2>&1 || true
  fi
  [[ -f "$RUNTIME_TAR" ]] && sudo tar -C "$CONTROL" --acls --xattrs --numeric-owner -xpf "$RUNTIME_TAR" >/dev/null 2>&1 || true
  echo 'ROLLBACK=ATTEMPTED'
}

on_exit(){
  local rc=$?
  if (( rc != 0 )); then
    rollback
    if (( QUIESCED )); then
      if (( ! MIGRATION_VERIFIED || SAFE_TO_RESTORE_WRITERS )); then
        restore_services
      else
        echo 'CONTROL_WRITERS_LEFT_STOPPED=YES'
        echo 'CONTROL_WRITERS_STOP_REASON=post-migration safety gate not complete'
      fi
    fi
    echo 'FINAL_STATUS=FAIL'
    echo "BACKUP=$BACKUP"
  else
    (( QUIESCED )) && restore_services
  fi
  exit "$rc"
}
trap on_exit EXIT

write_sums(){
  sudo bash -c '
    set -Eeuo pipefail; cd "$1"; shift
    for r in "$@"; do [[ -e "$r" ]] && find "$r" -type f -print0 || true; done |
      sort -z | xargs -0 -r sha256sum
  ' bash "$CONTROL" "${RUNTIME_PATHS[@]}" > "$RUNTIME_SUMS"
}

verify_sums(){ (cd "$CONTROL" && sudo sha256sum -c "$RUNTIME_SUMS"); }

stage 1 'PREFLIGHT'
[[ "$(id -un)" == joshan ]] || fail 1 'run as user joshan'
for c in git tar sha256sum python3 flock sudo systemctl install; do command -v "$c" >/dev/null || fail 1 "missing command: $c"; done
sudo -v || fail 1 'sudo authentication failed'
[[ -d "$CONTROL/.git" ]] || fail 1 "missing control repo: $CONTROL"
[[ -d "$PLATFORM/.git" ]] || fail 1 "missing canonical platform repo: $PLATFORM"
[[ "$(git -C "$CONTROL" branch --show-current)" == main ]] || fail 1 'control repo must be on main'
[[ "$(git -C "$PLATFORM" branch --show-current)" == main ]] || fail 1 'platform repo must be on main'
[[ -f /etc/lifeos-control/identity.json ]] || fail 1 'control identity missing'
OLD_HEAD="$(git -C "$CONTROL" rev-parse HEAD)"
mkdir -p "$BACKUP"
pass 1

stage 2 'CANONICAL SOURCE GATES'
[[ -z "$(git -C "$PLATFORM" status --porcelain --untracked-files=no)" ]] || fail 2 'platform tracked tree is dirty'
git -C "$PLATFORM" fetch origin main || fail 2 'platform fetch failed'
git -C "$PLATFORM" merge-base --is-ancestor "$SAFE_PLATFORM_COMMIT" origin/main || fail 2 'safe publisher/runner commit not in platform origin/main'
git -C "$PLATFORM" merge --ff-only origin/main || fail 2 'platform cannot fast-forward to origin/main'

while IFS= read -r p; do [[ -z "$p" ]] || is_runtime_path "$p" || fail 2 "unexpected tracked control change: $p"; done \
  < <({ git -C "$CONTROL" diff --name-only; git -C "$CONTROL" diff --cached --name-only; } | sort -u)
while IFS= read -r p; do [[ -z "$p" ]] || is_runtime_path "$p" || fail 2 "unexpected untracked control file: $p"; done \
  < <(git -C "$CONTROL" ls-files --others --exclude-standard)

git -C "$CONTROL" fetch origin main || fail 2 'control fetch failed'
git -C "$CONTROL" merge-base --is-ancestor "$CONTROL_OWNERSHIP_COMMIT" origin/main || fail 2 'control ownership commit not in origin/main'
remote_runtime="$(git -C "$CONTROL" ls-tree -r --name-only origin/main -- "${RUNTIME_PATHS[@]}")"
[[ -z "$remote_runtime" ]] || { printf '%s\n' "$remote_runtime"; fail 2 'origin/main still tracks runtime paths'; }
pass 2

stage 3 'STALE ACTIVATION SAFETY GATE'
manifest="$CONTROL/$STALE_MANIFEST"; script="$CONTROL/$STALE_SCRIPT"
result="$CONTROL/results/$STALE_ACTIVATION_ID.json"; archive="$CONTROL/jobs/archive/$STALE_ACTIVATION_ID.json"
if [[ -f "$manifest" ]]; then
  [[ ! -f "$result" && ! -f "$archive" ]] || fail 3 'stale activation exists both pending and completed'
  [[ -f "$script" ]] || fail 3 'stale activation script missing'
  [[ "$(sha "$script")" == "$STALE_SCRIPT_SHA" ]] || fail 3 'stale activation script checksum mismatch'
  python3 - "$manifest" "$STALE_SCRIPT" "$STALE_SCRIPT_SHA" <<'PY' || fail 3 'stale activation manifest malformed'
import json,sys
d=json.load(open(sys.argv[1])); rel,want=sys.argv[2:]
assert d['job_id']=='activate-engineer-v1-660a6d4862fa'
assert d['job_type']=='change' and d['change_scope']=='root-broker' and d['requires_root'] is True
assert d['change_policy']=='gated-v1' and d['script']==rel and d['script_sha256']==want
PY
  current_broker_sha="$(sha "$PLATFORM/homelab/live/usr/local/sbin/lifeos-root-broker")"
  old_approved_sha="$(grep -E '^readonly APPROVED_SHA=' "$script" | head -1 | cut -d= -f2)"
  echo "STALE_ACTIVATION_APPROVED_BROKER_SHA=$old_approved_sha"
  echo "CURRENT_CANONICAL_BROKER_SHA=$current_broker_sha"
  [[ "$old_approved_sha" != "$current_broker_sha" ]] || fail 3 'stale activation unexpectedly matches current broker; re-review required'
  echo 'STALE_ACTIVATION_STATE=pending-and-provably-obsolete'
elif [[ -f "$result" && -f "$archive" ]]; then
  echo 'STALE_ACTIVATION_STATE=already-complete'
else
  fail 3 'expected stale activation evidence is missing/inconsistent'
fi
pass 3

stage 4 'QUIESCE CONTROL WRITERS'
if systemctl is-active --quiet lifeos-control-job-submit.socket; then
  SUBMIT_SOCKET_WAS_ACTIVE=1
  sudo systemctl stop lifeos-control-job-submit.socket || fail 4 'cannot stop submission socket'
fi
while IFS= read -r u; do
  [[ -n "$u" ]] || continue
  if systemctl cat "$u" 2>/dev/null | grep -Eq 'lifeos-job-publisher|lifeos-pi-control-runner'; then
    systemctl is-active --quiet "$u" && ACTIVE_UNITS+=("$u") || true
  fi
done < <(systemctl list-unit-files --type=service --type=timer --no-legend 2>/dev/null | awk '{print $1}')
for u in "${ACTIVE_UNITS[@]}"; do sudo systemctl stop "$u" || fail 4 "cannot stop $u"; done
mkdir -p "$CONTROL/state" /home/joshan/.local/state/lifeos-pi-control
exec 8>"$CONTROL/state/publisher.lock"; flock -n 8 || fail 4 'publisher still active'
exec 9>/home/joshan/.local/state/lifeos-pi-control/runner.lock; flock -n 9 || fail 4 'runner still active'
pgrep -af 'lifeos-(job-publisher|pi-control-runner)' >/dev/null && fail 4 'control writer process remains active' || true
QUIESCED=1
pass 4

stage 5 'PRESERVE ALL RUNTIME STATE'
existing=(); for r in "${RUNTIME_PATHS[@]}"; do [[ -e "$CONTROL/$r" ]] && existing+=("$r"); done
((${#existing[@]} > 0)) || fail 5 'no runtime state found'
sudo tar -C "$CONTROL" --acls --xattrs --numeric-owner -cpf "$RUNTIME_TAR" "${existing[@]}" || fail 5 'runtime backup failed'
sudo chown joshan:joshan "$RUNTIME_TAR"
write_sums || fail 5 'checksum inventory failed'
[[ -s "$RUNTIME_TAR" ]] || fail 5 'runtime backup empty'
sha "$RUNTIME_TAR" > "$BACKUP/runtime.tar.sha256"
[[ -f "$manifest" ]] && cp -a "$manifest" "$BACKUP/stale-activation-manifest.json" || true
[[ -f "$script" ]] && cp -a "$script" "$BACKUP/stale-activation-script.sh" || true
sync
pass 5

stage 6 'MIGRATE GIT OWNERSHIP AND RESTORE RUNTIME BYTES'
MUTATION_STARTED=1
for r in "${RUNTIME_PATHS[@]}"; do sudo rm -rf "$CONTROL/$r"; done
tracked=()
for r in "${RUNTIME_PATHS[@]}"; do git -C "$CONTROL" ls-tree -r --name-only HEAD -- "$r" | grep -q . && tracked+=("$r") || true; done
((${#tracked[@]} == 0)) || git -C "$CONTROL" restore --source=HEAD --staged --worktree -- "${tracked[@]}" || fail 6 'cannot normalize old tracked runtime snapshot'
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 6 'control tree not clean before fast-forward'
git -C "$CONTROL" merge-base --is-ancestor HEAD origin/main || fail 6 'local control HEAD is not ancestor of origin/main'
git -C "$CONTROL" merge --ff-only origin/main || fail 6 'control fast-forward failed'
[[ -z "$(git -C "$CONTROL" ls-files -- "${RUNTIME_PATHS[@]}")" ]] || fail 6 'runtime paths remain Git-owned'
sudo tar -C "$CONTROL" --acls --xattrs --numeric-owner -xpf "$RUNTIME_TAR" || fail 6 'runtime restore failed'
verify_sums >/dev/null || fail 6 'restored runtime bytes differ from backup'
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 6 'static control tree dirty after restore'
MIGRATION_VERIFIED=1
pass 6

stage 7 'INSTALL PINNED SAFE PUBLISHER AND RUNNER'
mkdir -p "$BACKUP/bin"
[[ -f "$PUBLISHER" ]] && sudo cp -a "$PUBLISHER" "$BACKUP/bin/lifeos-job-publisher.pre" || true
[[ -f "$RUNNER" ]] && sudo cp -a "$RUNNER" "$BACKUP/bin/lifeos-pi-control-runner.pre" || true
pub_tmp="$(mktemp)"; run_tmp="$(mktemp)"
git -C "$PLATFORM" show "$SAFE_PLATFORM_COMMIT:homelab/live/usr/local/sbin/lifeos-job-publisher" > "$pub_tmp" || fail 7 'cannot extract pinned publisher'
git -C "$PLATFORM" show "$SAFE_PLATFORM_COMMIT:homelab/live/usr/local/sbin/lifeos-pi-control-runner" > "$run_tmp" || fail 7 'cannot extract pinned runner'
python3 -m py_compile "$pub_tmp" "$run_tmp" || fail 7 'pinned binaries fail compile'
grep -Fq '+refs/heads/main:refs/remotes/origin/main' "$pub_tmp" || fail 7 'publisher safe-fetch marker missing'
grep -Fq 'jobs/staged' "$pub_tmp" || fail 7 'publisher legacy guard missing'
grep -Fq '"persistence": "local-runtime"' "$run_tmp" || fail 7 'runner local-runtime marker missing'
for bad in 'git("push"' 'git("rebase"' 'git("add"'; do grep -Fq "$bad" "$run_tmp" && fail 7 "runner forbidden Git mutation remains: $bad" || true; done
sudo install -o root -g root -m 0755 "$pub_tmp" "$PUBLISHER" || fail 7 'publisher install failed'
sudo install -o root -g root -m 0755 "$run_tmp" "$RUNNER" || fail 7 'runner install failed'
[[ "$(sha "$PUBLISHER")" == "$(sha "$pub_tmp")" ]] || fail 7 'publisher checksum mismatch after install'
[[ "$(sha "$RUNNER")" == "$(sha "$run_tmp")" ]] || fail 7 'runner checksum mismatch after install'
rm -f "$pub_tmp" "$run_tmp"
pass 7

stage 8 'QUARANTINE OBSOLETE ACTIVATION WITHOUT CONSUMING IT'
if [[ -f "$CONTROL/$STALE_MANIFEST" ]]; then
  qdir="$CONTROL/state/quarantined-jobs"; mkdir -p "$qdir"
  qmanifest="$qdir/${STALE_ACTIVATION_ID}.${STAMP}.json"
  mv "$CONTROL/$STALE_MANIFEST" "$qmanifest" || fail 8 'cannot quarantine stale activation manifest'
  python3 - "$qdir/${STALE_ACTIVATION_ID}.${STAMP}.reason.json" "$qmanifest" <<'PY' || fail 8 'cannot write quarantine reason'
import datetime,json,sys
out,manifest=sys.argv[1:]
d={
 'schema_version':1,'job_id':'activate-engineer-v1-660a6d4862fa','status':'QUARANTINED_SUPERSEDED',
 'reason':'assured root-broker bytes no longer match canonical main; do not execute stale activation',
 'manifest':manifest,'quarantined_at':datetime.datetime.now(datetime.timezone.utc).isoformat()
}
with open(out,'x') as f: json.dump(d,f,indent=2); f.write('\n')
PY
  [[ ! -f "$CONTROL/$STALE_MANIFEST" && -f "$qmanifest" ]] || fail 8 'stale activation quarantine verification failed'
  echo "STALE_ACTIVATION_QUARANTINED=$qmanifest"
else
  echo 'STALE_ACTIVATION_QUARANTINE=not-needed-already-complete'
fi
SAFE_TO_RESTORE_WRITERS=1
pass 8

stage 9 'REGRESSION GATES'
[[ -z "$(git -C "$CONTROL" ls-files -- "${RUNTIME_PATHS[@]}")" ]] || fail 9 'runtime path became tracked again'
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 9 'static control tree is dirty'
for x in jobs/pending/ results/ state/; do grep -Fxq "$x" "$CONTROL/.gitignore" || fail 9 "gitignore missing $x"; done
grep -Fq 'local-runtime' "$RUNNER" || fail 9 'safe runner not live'
grep -Fq 'jobs/staged' "$PUBLISHER" || fail 9 'safe publisher not live'
/usr/local/sbin/lifeos-ansible-adopt --status > "$BACKUP/v3-status.txt" 2>&1 || fail 9 'V3 baseline failed after migration'
pass 9

stage 10 'LIVE EVIDENCE FOR FRESH ACTIVATION'
echo "LIVE_ROOT_BROKER_SHA256=$(sha /usr/local/sbin/lifeos-root-broker 2>/dev/null || echo MISSING)"
echo "CANONICAL_ROOT_BROKER_SHA256=$(sha "$PLATFORM/homelab/live/usr/local/sbin/lifeos-root-broker")"
echo "LIVE_PUBLISHER_SHA256=$(sha "$PUBLISHER")"
echo "LIVE_RUNNER_SHA256=$(sha "$RUNNER")"
echo "CONTROL_HEAD=$(git -C "$CONTROL" rev-parse HEAD)"
echo "PLATFORM_HEAD=$(git -C "$PLATFORM" rev-parse HEAD)"
echo "PENDING_COUNT=$(find "$CONTROL/jobs/pending" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l)"
echo "ARCHIVE_COUNT=$(find "$CONTROL/jobs/archive" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l)"
echo "RESULT_COUNT=$(find "$CONTROL/results" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l)"
if [[ -S /run/lifeos-root-broker.sock ]]; then echo 'ROOT_BROKER_SOCKET=present'; else echo 'ROOT_BROKER_SOCKET=absent'; fi
for url in http://127.0.0.1:8790/health http://127.0.0.1:8793/health; do
  python3 - "$url" <<'PY' || true
import json,sys,urllib.request
u=sys.argv[1]
try:
    with urllib.request.urlopen(u,timeout=5) as r: d=json.load(r)
    print('HEALTH_'+u.split(':')[2].split('/')[0]+'='+str(d.get('status','unknown')))
except Exception as e: print('HEALTH_'+u.split(':')[2].split('/')[0]+'=unavailable:'+type(e).__name__)
PY
done
pass 10

restore_services
ACTIVE_UNITS=(); SUBMIT_SOCKET_WAS_ACTIVE=0; QUIESCED=0
trap - EXIT
echo 'FINAL_STATUS=PASS'
echo "BACKUP=$BACKUP"
echo 'NEXT_REQUIRED=fresh_engineer_activation_from_live_evidence'
