#!/usr/bin/env bash
set -Eeuo pipefail

readonly CONTROL=/home/joshan/lifeos-pi-control
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly BACKUP="/home/joshan/lifeos-control-runtime-backups/${STAMP}-legacy-executable-residue"
readonly TAR="$BACKUP/legacy-executable-residue.tar"
readonly SUMS="$BACKUP/legacy-executable-residue.sha256"

readonly BROKER_BLOB=225c61b81452eee6924039e1ab24578f84e966a3
readonly PUBLISHER_BLOB=f5e0ca0e76a348f76e2325c23e3c92273ee8be25
readonly RUNNER_BLOB=127180b1376af17bda759e24f6b0949d93381726

fail(){
  echo 'CLEANER_STATUS=FAIL'
  echo "FAIL_REASON=$*"
  echo "BACKUP=$BACKUP"
  exit 1
}

[[ "$(id -un)" == joshan ]] || fail 'must run as joshan'
[[ -d "$CONTROL/.git" ]] || fail 'control repo missing'
[[ "$(git -C "$CONTROL" branch --show-current)" == main ]] || fail 'control repo not on main'
mkdir -p "$BACKUP"
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 'tracked control tree is dirty'

check_optional_source(){
  local rel expected path actual
  rel="$1"; expected="$2"; path="$CONTROL/$rel"
  if [[ ! -e "$path" ]]; then
    echo "LEGACY_SOURCE_STATE=$rel:already-removed"
    return 0
  fi
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe legacy source: $rel"
  actual="$(git hash-object "$path")"
  [[ "$actual" == "$expected" ]] || fail "legacy source blob mismatch: $rel actual=$actual expected=$expected"
  echo "LEGACY_SOURCE_STATE=$rel:exact-former-blob"
}

check_optional_source broker/lifeos-root-broker "$BROKER_BLOB"
check_optional_source publisher/lifeos-job-publisher "$PUBLISHER_BLOB"
check_optional_source runner/lifeos-pi-control-runner "$RUNNER_BLOB"

is_runtime(){
  case "$1" in
    jobs/staging/*|jobs/staged/*|jobs/pending/*|jobs/archive/*|jobs/scripts/*|jobs/change-scripts/*|jobs/root-scripts/*|results/*|state/*) return 0 ;;
    *) return 1 ;;
  esac
}

for root in broker publisher runner; do
  [[ -e "$CONTROL/$root" ]] || continue
  while IFS= read -r -d '' path; do
    rel="${path#"$CONTROL/"}"
    case "$rel" in
      "$root"|"$root/__pycache__"|"$root/__pycache__/"*.pyc|"$root/lifeos-root-broker"|"$root/lifeos-job-publisher"|"$root/lifeos-pi-control-runner") ;;
      *) fail "unexpected legacy residue path: $rel" ;;
    esac
    [[ ! -L "$path" ]] || fail "symlink not permitted in legacy residue: $rel"
  done < <(find "$CONTROL/$root" -mindepth 0 -print0)
done

while IFS= read -r p; do
  [[ -z "$p" ]] && continue
  case "$p" in broker/*|publisher/*|runner/*) ;;
    *) is_runtime "$p" || fail "unexpected untracked control file outside legacy residue: $p" ;;
  esac
done < <(git -C "$CONTROL" ls-files --others --exclude-standard)

existing=()
for root in broker publisher runner; do [[ -e "$CONTROL/$root" ]] && existing+=("$root"); done
if ((${#existing[@]})); then
  (cd "$CONTROL" && find "${existing[@]}" -type f -print0 | sort -z | xargs -0 -r sha256sum) > "$SUMS"
  tar -C "$CONTROL" --acls --xattrs -cpf "$TAR" "${existing[@]}"
  [[ -s "$TAR" ]] || fail 'legacy residue backup is empty'
  sha256sum "$TAR" > "$BACKUP/legacy-executable-residue.tar.sha256"
  sync
  rm -rf "$CONTROL/broker" "$CONTROL/publisher" "$CONTROL/runner"
else
  echo 'LEGACY_RESIDUE_STATE=already-clean'
fi

[[ ! -e "$CONTROL/broker" && ! -e "$CONTROL/publisher" && ! -e "$CONTROL/runner" ]] || fail 'legacy directories remain after cleanup'
while IFS= read -r p; do
  [[ -z "$p" ]] && continue
  is_runtime "$p" || fail "unexpected untracked control file remains: $p"
done < <(git -C "$CONTROL" ls-files --others --exclude-standard)
[[ -z "$(git -C "$CONTROL" status --porcelain --untracked-files=no)" ]] || fail 'tracked control tree changed during cleanup'

echo 'CLEANER_STATUS=PASS'
echo "BACKUP=$BACKUP"
echo 'NEXT_REQUIRED=run_control_runtime_ownership_migration'
