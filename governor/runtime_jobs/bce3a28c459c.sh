#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL=/home/joshan/lifeos-pi-control
readonly RELAY_JOB=0019-two-repo-migration-gate
readonly MIGRATION_COMMIT=3a93d6e9e99fe04f62f8a452b688639cefb05b82
readonly ENERGY_TREE=d9a4d225cd16663ec1ed5f0f909b615e4c1f9b91
readonly WAIT_SECONDS=900

emit() {
  printf '%s\n' \
    "ISSUE_VALIDITY=$1" "LIFEOS_WORK_STATE=$2" "BARRIER=$3" \
    "NEXT_AUTONOMOUS_ACTION=$4" 'DISCOVERED_ISSUES_JSON_B64=none' \
    "RESULT=$5" "TESTS=$6" "NEXT_RUNTIME_CHECK=$7"
}

fail() {
  printf 'FAIL=%s\n' "$1" >&2
  emit VALID BLOCKED "$1" \
    'repair the named migration-gate barrier, then rerun this launcher through Watchman' \
    RETRY 'Pi migration gate failed closed' \
    'bash governor/runtime_jobs/bce3a28c459c.sh'
  exit 1
}

run() { timeout --signal=TERM --kill-after=10s "$@"; }

for tool in git python3 sha256sum timeout; do
  command -v "$tool" >/dev/null || fail "${tool}_missing"
done
[[ -d "$PLATFORM/.git" ]] || fail pi_canonical_platform_checkout_missing
[[ -d "$CONTROL/.git" ]] || fail pi_control_relay_checkout_missing
[[ -z $(run 15s git -C "$PLATFORM" status --porcelain --untracked-files=no) ]] || fail pi_canonical_platform_checkout_dirty

origin=$(run 15s git -C "$PLATFORM" remote get-url origin) || fail pi_canonical_platform_origin_missing
normalized=${origin%.git}
normalized=${normalized/github.com:/github.com/}
[[ "$normalized" == *github.com/joshant20-ops/lifeos-platform ]] || fail pi_canonical_platform_origin_mismatch
run 120s git -C "$PLATFORM" fetch --prune origin main || fail pi_canonical_platform_fetch_failed
local_head=$(run 15s git -C "$PLATFORM" rev-parse HEAD) || fail pi_canonical_platform_head_unreadable
remote_head=$(run 15s git -C "$PLATFORM" rev-parse refs/remotes/origin/main) || fail pi_canonical_platform_remote_head_unreadable
run 15s git -C "$PLATFORM" merge-base --is-ancestor "$local_head" "$remote_head" || fail pi_canonical_platform_non_fast_forward
if [[ "$local_head" != "$remote_head" ]]; then
  run 30s git -C "$PLATFORM" merge --ff-only "$remote_head" || fail pi_canonical_platform_fast_forward_failed
fi
printf 'PI_CANONICAL_CHECKOUT=PASS commit=%s\n' "$remote_head"

run 15s git -C "$PLATFORM" cat-file -e "${MIGRATION_COMMIT}^{commit}" || fail migration_commit_missing
tree=$(run 15s git -C "$PLATFORM" rev-parse "$MIGRATION_COMMIT:energy") || fail migration_energy_tree_unreadable
[[ "$tree" == "$ENERGY_TREE" ]] || fail migration_energy_tree_identity_mismatch
run 15s git -C "$PLATFORM" merge-base --is-ancestor "$MIGRATION_COMMIT" HEAD || fail migration_commit_not_in_canonical_history
printf 'ENERGY_OBJECT_IDENTITY=PASS commit=%s tree=%s\n' "$MIGRATION_COMMIT" "$tree"

manifest=''
shopt -s nullglob
candidates=(
  "$CONTROL/jobs/staging/$RELAY_JOB.json"
  "$CONTROL/jobs/pending/$RELAY_JOB.json"
  "$CONTROL/jobs/archive/$RELAY_JOB.json"
  "$CONTROL/jobs/archive/$RELAY_JOB".*.json
)
shopt -u nullglob
for candidate in "${candidates[@]}"; do
  if [[ -f "$candidate" && ! -L "$candidate" ]]; then
    [[ -z "$manifest" ]] || fail duplicate_0019_manifest
    manifest=$candidate
  fi
done
[[ -n "$manifest" ]] || fail queued_0019_manifest_missing

# Generic commit/path/hash names are accepted only inside the immutable-source
# object. Repository identity may be declared there or once at manifest level,
# matching both documented relay encodings without confusing wrapper metadata.
identity=$(python3 - "$manifest" <<'PY'
import json, re, sys

with open(sys.argv[1], encoding="utf-8") as stream:
    data = json.load(stream)

def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)

source_keys = {"canonical_source", "immutable_source", "source"}
sources = [child for obj in objects(data) for key, child in obj.items()
           if str(key).lower() in source_keys and isinstance(child, dict)]
if len(sources) != 1:
    raise SystemExit("expected exactly one immutable source object")
source = sources[0]

def value(obj, keys):
    matches = [v for k, v in obj.items() if str(k).lower() in keys and isinstance(v, str)]
    if len(matches) != 1:
        raise SystemExit("missing or ambiguous field: " + "/".join(sorted(keys)))
    return matches[0]

repo_keys = {"canonical_repository", "source_repository", "repository", "repo"}
source_repos = [v for k, v in source.items() if str(k).lower() in repo_keys and isinstance(v, str)]
if source_repos:
    if len(source_repos) != 1:
        raise SystemExit("ambiguous source repository")
    repo = source_repos[0]
else:
    # Compatibility with the queued 0019 manifest: repository identity can be
    # top-level while immutable artifact fields remain scoped to source.
    repo = value(data, repo_keys)
commit = value(source, {"commit", "commit_sha", "immutable_commit", "source_commit", "source_commit_sha"})
path = value(source, {"canonical_script", "canonical_script_path", "script_path", "source_path", "path"})
digest = value(source, {"canonical_script_sha256", "script_sha256", "source_script_sha256", "source_sha256", "sha256"})

normalized = repo.rstrip("/").removesuffix(".git").replace("github.com:", "github.com/")
assert normalized.endswith("github.com/joshant20-ops/lifeos-platform"), "wrong canonical repository"
assert re.fullmatch(r"[0-9a-f]{40}", commit), "invalid commit"
assert path and not path.startswith("/") and ".." not in path.split("/"), "unsafe path"
assert re.fullmatch(r"[0-9a-f]{64}", digest), "invalid sha256"
print(commit); print(path); print(digest)
PY
) || fail invalid_0019_manifest
readarray -t fields <<<"$identity"
[[ ${#fields[@]} -eq 3 ]] || fail incomplete_0019_manifest_identity
source_commit=${fields[0]}; source_path=${fields[1]}; source_sha=${fields[2]}
run 15s git -C "$PLATFORM" cat-file -e "${source_commit}^{commit}" || fail manifest_source_commit_missing
[[ $(run 15s git -C "$PLATFORM" rev-parse "$source_commit:energy") == "$ENERGY_TREE" ]] || fail manifest_source_lacks_imported_energy_identity
actual_sha=$(run 15s git -C "$PLATFORM" show "$source_commit:$source_path" | sha256sum | awk '{print $1}') || fail manifest_canonical_script_unreadable
[[ "$actual_sha" == "$source_sha" ]] || fail manifest_canonical_script_hash_mismatch
printf 'IMMUTABLE_SOURCE_MANIFEST=PASS commit=%s path=%s sha256=%s\n' "$source_commit" "$source_path" "$source_sha"

result="$CONTROL/results/$RELAY_JOB.json"
if [[ ! -f "$result" ]]; then
  systemctl start --no-block lifeos-pi-control-runner.service 2>/dev/null || fail relay_runner_start_failed
  deadline=$((SECONDS + WAIT_SECONDS))
  while [[ ! -f "$result" && $SECONDS -lt $deadline ]]; do sleep 2; done
fi
[[ -f "$result" && ! -L "$result" ]] || fail pi_0019_result_timeout
python3 - "$result" <<'PY' || fail pi_0019_result_not_pass
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    result = json.load(stream)
assert result.get("classification") == "PASS", result.get("classification", "missing")
print("PI_RELAY_RESULT=PASS")
PY

emit ALREADY_COMPLETE PASS none \
  'retain migration evidence and proceed to the next repository-model migration gate' \
  PASS 'canonical checkout, energy object identity, immutable source, and relay result PASS' none
