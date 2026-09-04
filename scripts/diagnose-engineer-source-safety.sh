#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly BROKER=/usr/local/sbin/lifeos-root-broker
readonly EXPECTED_BROKER_SHA=a9da48216ad261631be29216e001d52306f6981fb07e35727d8b38b92f02b309
readonly SOURCES=(
  governor/autonomous_agent.py
  governor/target_identity.py
  governor/engineer_backend.py
)

stage(){ printf '\n===== STAGE %s — %s =====\n' "$1" "$2"; }
pass(){ printf 'STAGE_%s=PASS\n' "$1"; }
fail(){ local s="$1"; shift; printf 'STAGE_%s=FAIL\nFAIL_REASON=%s\n' "$s" "$*" >&2; exit 1; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

stage 1 'READ-ONLY PREFLIGHT'
[[ -d "$PLATFORM/.git" ]] || fail 1 'platform repository missing'
[[ -f "$BROKER" ]] || fail 1 'root broker missing'
[[ "$(sha "$BROKER")" == "$EXPECTED_BROKER_SHA" ]] || fail 1 'unexpected live broker hash'
HEAD="$(git -C "$PLATFORM" rev-parse HEAD)"
MAIN="$(git -C "$PLATFORM" rev-parse main)"
ORIGIN="$(git -C "$PLATFORM" rev-parse refs/remotes/origin/main)"
[[ "$HEAD" == "$MAIN" && "$HEAD" == "$ORIGIN" ]] || fail 1 'platform is not checked out at published main'
[[ -z "$(git -C "$PLATFORM" status --porcelain --untracked-files=no)" ]] || fail 1 'platform tracked tree dirty'
REPO_UID="$(stat -c %u "$PLATFORM")"
REPO_GID="$(stat -c %g "$PLATFORM")"
REPO_MODE="$(stat -c %a "$PLATFORM")"
printf 'SOURCE_COMMIT=%s\n' "$HEAD"
printf 'REPO_UID=%s\nREPO_GID=%s\nREPO_MODE=%s\n' "$REPO_UID" "$REPO_GID" "$REPO_MODE"
pass 1

stage 2 'EXACT BROKER SOURCE-SAFETY PREDICATE'
unsafe=0
for rel in "${SOURCES[@]}"; do
  path="$PLATFORM/$rel"
  if [[ ! -e "$path" ]]; then
    printf 'SOURCE=%s STATE=missing\n' "$rel"
    unsafe=1
    continue
  fi
  type="$(stat -c %F "$path")"
  uid="$(stat -c %u "$path")"
  gid="$(stat -c %g "$path")"
  mode="$(stat -c %a "$path")"
  perms="$(stat -c %A "$path")"
  actual_sha="$(sha "$path")"
  git_sha="$(git -C "$PLATFORM" show "$HEAD:$rel" | sha256sum | awk '{print $1}')"
  tracked=no
  git -C "$PLATFORM" ls-files --error-unmatch -- "$rel" >/dev/null 2>&1 && tracked=yes
  regular=no
  [[ -f "$path" && ! -L "$path" ]] && regular=yes
  owner_match=no
  [[ "$uid" == "$REPO_UID" ]] && owner_match=yes
  writable_forbidden=no
  mode_num=$((8#$mode))
  (( mode_num & 0022 )) && writable_forbidden=yes
  checksum_match=no
  [[ "$actual_sha" == "$git_sha" ]] && checksum_match=yes
  safe=no
  [[ "$regular" == yes && "$owner_match" == yes && "$writable_forbidden" == no && "$checksum_match" == yes && "$tracked" == yes ]] && safe=yes || unsafe=1
  printf 'SOURCE=%s TYPE=%q UID=%s GID=%s MODE=%s PERMS=%s TRACKED=%s REGULAR=%s OWNER_MATCH=%s GROUP_OR_OTHER_WRITABLE=%s CHECKSUM_MATCH=%s SAFE=%s\n' \
    "$rel" "$type" "$uid" "$gid" "$mode" "$perms" "$tracked" "$regular" "$owner_match" "$writable_forbidden" "$checksum_match" "$safe"
done
if (( unsafe )); then
  echo 'BROKER_SOURCE_SAFETY=FAIL'
else
  echo 'BROKER_SOURCE_SAFETY=PASS'
fi
pass 2

stage 3 'FAILED ACTIVATION EVIDENCE PRESERVATION'
for id in engineer-current-20260904 engineer-current-20260904-v2; do
  approval="/var/lib/lifeos-control/engineer-deploy-approvals/$id.json"
  audit="/var/lib/lifeos-control/engineer-deploy-audit/$id.json"
  printf 'JOB_ID=%s APPROVAL=%s AUDIT=%s\n' "$id" "$([[ -f "$approval" ]] && echo present || echo absent)" "$([[ -f "$audit" ]] && echo present || echo absent)"
done
pass 3

echo 'FINAL_STATUS=PASS'
echo 'MUTATION_PERFORMED=NO'
echo 'NEXT_REQUIRED=repair_source_metadata_from_exact_evidence'
