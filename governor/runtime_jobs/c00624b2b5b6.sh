#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly CONTROL=/home/joshan/lifeos-pi-control
readonly JOB_ID=0019-two-repo-migration-gate
readonly MIGRATION_COMMIT=3a93d6e9e99fe04f62f8a452b688639cefb05b82
readonly ENERGY_TREE=d9a4d225cd16663ec1ed5f0f909b615e4c1f9b91
readonly DEADLINE_SECONDS=900
readonly PLATFORM_REPOSITORY=joshant20-ops/lifeos-platform

emit() {
  printf '%s\n' \
    "ISSUE_VALIDITY=$1" \
    "LIFEOS_WORK_STATE=$2" \
    "BARRIER=$3" \
    "NEXT_AUTONOMOUS_ACTION=$4" \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    "RESULT=$5" \
    "TESTS=$6" \
    "NEXT_RUNTIME_CHECK=$7"
}

fail() {
  printf 'FAIL=%s\n' "$1" >&2
  emit VALID BLOCKED "$1" \
    'repair the named Pi migration-gate barrier and rerun this launcher' \
    RETRY 'two-repository migration gate failed closed' \
    'bash governor/runtime_jobs/c00624b2b5b6.sh'
  exit 1
}

run() { timeout --signal=TERM --kill-after=10s "$@"; }

command -v git >/dev/null || fail git_missing
command -v python3 >/dev/null || fail python3_missing
command -v sha256sum >/dev/null || fail sha256sum_missing
command -v timeout >/dev/null || fail timeout_missing
[[ -d "$PLATFORM/.git" ]] || fail pi_canonical_platform_checkout_missing
[[ -d "$CONTROL/.git" ]] || fail pi_control_relay_checkout_missing

# The Pi is the canonical Git writer.  Repair a stale checkout only by a clean,
# fast-forward update from its already-configured canonical origin; never
# replace local work or manufacture a second checkout.
[[ -z $(run 15s git -C "$PLATFORM" status --porcelain --untracked-files=no) ]] || fail pi_canonical_platform_checkout_dirty
origin_url=$(run 15s git -C "$PLATFORM" remote get-url origin) || fail pi_canonical_platform_origin_missing
normalized_origin=${origin_url%.git}
normalized_origin=${normalized_origin/github.com:/github.com/}
[[ "$normalized_origin" == *"github.com/${PLATFORM_REPOSITORY}" ]] || fail pi_canonical_platform_origin_mismatch
run 120s git -C "$PLATFORM" fetch --prune origin main || fail pi_canonical_platform_fetch_failed
local_head=$(run 15s git -C "$PLATFORM" rev-parse HEAD) || fail pi_canonical_platform_head_unreadable
remote_head=$(run 15s git -C "$PLATFORM" rev-parse refs/remotes/origin/main) || fail pi_canonical_platform_remote_head_unreadable
run 15s git -C "$PLATFORM" merge-base --is-ancestor "$local_head" "$remote_head" || fail pi_canonical_platform_non_fast_forward
if [[ "$local_head" != "$remote_head" ]]; then
  run 30s git -C "$PLATFORM" merge --ff-only "$remote_head" || fail pi_canonical_platform_fast_forward_failed
fi
printf 'PI_CANONICAL_CHECKOUT=PASS commit=%s\n' "$remote_head"

# Prove the imported bytes still have the exact object identity recorded at the
# canonical migration commit. This reads Git objects only and emits no content.
run 15s git -C "$PLATFORM" cat-file -e "${MIGRATION_COMMIT}^{commit}" || fail migration_commit_missing
migration_tree=$(run 15s git -C "$PLATFORM" rev-parse "$MIGRATION_COMMIT:energy") || fail migration_energy_tree_unreadable
[[ "$migration_tree" == "$ENERGY_TREE" ]] || fail migration_energy_tree_identity_mismatch
run 15s git -C "$PLATFORM" merge-base --is-ancestor "$MIGRATION_COMMIT" HEAD || fail migration_commit_not_in_canonical_history
printf 'ENERGY_OBJECT_IDENTITY=PASS commit=%s tree=%s\n' "$MIGRATION_COMMIT" "$ENERGY_TREE"

manifest=''
shopt -s nullglob
manifest_candidates=(
  "$CONTROL/jobs/staging/$JOB_ID.json"
  "$CONTROL/jobs/pending/$JOB_ID.json"
  "$CONTROL/jobs/archive/$JOB_ID.json"
  "$CONTROL/jobs/archive/$JOB_ID".*.json
)
shopt -u nullglob
for candidate in "${manifest_candidates[@]}"; do
  if [[ -f "$candidate" && ! -L "$candidate" ]]; then
    [[ -z "$manifest" ]] || fail duplicate_0019_manifest
    manifest=$candidate
  fi
done
[[ -n "$manifest" ]] || fail queued_0019_manifest_missing

# Validate the relay request names canonical immutable source. The validator
# accepts nested manifests and common field spellings, but every contract value
# is mandatory and is then independently checked against the platform object.
identity_output=$(python3 - "$manifest" <<'PY'
import json, re, sys

d = json.load(open(sys.argv[1], encoding="utf-8"))

def pairs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower(), child
            yield from pairs(child)
    elif isinstance(value, list):
        for child in value:
            yield from pairs(child)

source_keys = {"canonical_source", "immutable_source", "source"}

def source_objects(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in source_keys and isinstance(child, dict):
                yield child
            yield from source_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from source_objects(child)

sources = list(source_objects(d))
if len(sources) > 1:
    raise SystemExit("ambiguous immutable source objects")
source = sources[0] if sources else None

if source is not None:
    # The relay protocol's compact source object uses repo/commit/path/sha256.
    # Scope those generic names to this object so wrapper hashes elsewhere in
    # the manifest cannot be mistaken for canonical source identity.
    items = list(pairs(source))
else:
    items = list(pairs(d))

def first(keys, predicate=lambda value: True):
    for key, value in items:
        if key in keys and isinstance(value, str) and predicate(value):
            return value
    raise SystemExit("missing manifest field: " + "/".join(sorted(keys)))

repo = first({"canonical_repository", "source_repository", "repository", "repo"},
             lambda v: v.rstrip("/").removesuffix(".git").endswith("joshant20-ops/lifeos-platform"))
commit = first({"commit", "commit_sha", "immutable_commit", "source_commit", "source_commit_sha"},
               lambda v: re.fullmatch(r"[0-9a-f]{40}", v) is not None)
path = first({"canonical_script", "canonical_script_path", "script_path", "source_path", "path"},
             lambda v: not v.startswith("/") and ".." not in v.split("/"))
digest = first({"canonical_script_sha256", "script_sha256", "source_script_sha256", "source_sha256", "sha256"},
               lambda v: re.fullmatch(r"[0-9a-f]{64}", v) is not None)
print(repo)
print(commit)
print(path)
print(digest)
PY
) || fail invalid_0019_manifest
readarray -t identity <<<"$identity_output"
[[ ${#identity[@]} -eq 4 ]] || fail incomplete_0019_manifest_identity
source_commit=${identity[1]}
source_path=${identity[2]}
source_sha=${identity[3]}
run 15s git -C "$PLATFORM" cat-file -e "${source_commit}^{commit}" || fail manifest_source_commit_missing
[[ $(run 15s git -C "$PLATFORM" rev-parse "$source_commit:energy") == "$ENERGY_TREE" ]] || fail manifest_source_lacks_imported_energy_identity
actual_sha=$(run 15s git -C "$PLATFORM" show "$source_commit:$source_path" | sha256sum | awk '{print $1}') || fail manifest_canonical_script_unreadable
[[ "$actual_sha" == "$source_sha" ]] || fail manifest_canonical_script_hash_mismatch
printf 'IMMUTABLE_SOURCE_MANIFEST=PASS commit=%s path=%s sha256=%s\n' "$source_commit" "$source_path" "$source_sha"

result="$CONTROL/results/$JOB_ID.json"
if [[ ! -f "$result" ]]; then
  systemctl start --no-block lifeos-pi-control-runner.service 2>/dev/null || fail relay_runner_start_failed
  deadline=$((SECONDS + DEADLINE_SECONDS))
  while [[ ! -f "$result" && $SECONDS -lt $deadline ]]; do
    sleep 2
  done
fi
[[ -f "$result" && ! -L "$result" ]] || fail pi_0019_result_timeout
python3 - "$result" <<'PY' || fail pi_0019_result_not_pass
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d.get("classification") == "PASS", d.get("classification", "missing")
print("PI_RELAY_RESULT=PASS")
PY

emit ALREADY_COMPLETE PASS none \
  'retain migration evidence and proceed to the next repository-model migration gate' \
  PASS 'energy Git object identity, immutable-source manifest, and Pi relay result PASS' none
