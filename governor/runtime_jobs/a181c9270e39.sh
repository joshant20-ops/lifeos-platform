#!/usr/bin/env bash
set -Eeuo pipefail

# Post-event closure for GitHub issue #25. Watchman is the only intended
# caller. The expired 2026-09-01 event is never replayed; historical evidence
# is validated after exact protected deployment and two safe post-event runs.
readonly JOB_ID=a181c9270e39
readonly REPO=/home/joshan/lifeos-platform
readonly SOURCE="$REPO/homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
readonly LIVE=/usr/local/sbin/lifeos-powerdown-assurance-active
readonly STATUS=/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json
readonly EVIDENCE=/opt/lifeos-watch/octopus-powerdown-assurance/event-evidence-v52.jsonl
readonly SERVICE=lifeos-powerdown-assurance-active.service
readonly FIX_COMMIT=6968eb4ea119f371a49960630cc7a4e62a094943
readonly APPROVED_SHA=fd7b1ce6e89bfd195fd86cb03a39f3c0ad592dc04d2091232f027f28375e23e7

run() { local limit=$1; shift; timeout --signal=TERM --kill-after=10s "$limit" "$@"; }
sha() { sha256sum "$1" | awk '{print $1}'; }
fail() {
  local barrier=$1
  printf 'FAIL=%s\n' "$barrier"
  printf '%s\n' \
    'ISSUE_VALIDITY=VALID' \
    'LIFEOS_WORK_STATE=BLOCKED' \
    "BARRIER=$barrier" \
    'NEXT_AUTONOMOUS_ACTION=preserve fail-closed state and correct only the named runtime barrier through Watchman' \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    'RESULT=BLOCKED' \
    'TESTS=runtime acceptance failed' \
    "NEXT_RUNTIME_CHECK=rerun governor/runtime_jobs/$JOB_ID.sh through Watchman after correcting $barrier"
  exit 1
}

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
[[ -d "$REPO/.git" ]] || fail canonical_repository_missing
head=$(git -C "$REPO" rev-parse HEAD)
[[ "$head" == "$(git -C "$REPO" rev-parse main)" ]] || fail canonical_head_not_main
[[ "$head" == "$(git -C "$REPO" rev-parse refs/remotes/origin/main)" ]] || fail canonical_main_not_published
git -C "$REPO" merge-base --is-ancestor "$FIX_COMMIT" "$head" || fail canonical_fix_commit_missing
[[ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]] || fail canonical_repository_dirty
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail canonical_source_missing_or_symlink
[[ "$(sha "$SOURCE")" == "$APPROVED_SHA" ]] || fail canonical_source_hash_mismatch
run 20s python3 -m py_compile "$SOURCE" || fail canonical_source_syntax
[[ "$(git -C "$REPO" diff-tree --no-commit-id --name-only -r "$FIX_COMMIT" | wc -l)" -eq 1 ]] || fail canonical_commit_scope_mismatch
[[ "$(git -C "$REPO" diff-tree --no-commit-id --name-only -r "$FIX_COMMIT")" == "${SOURCE#"$REPO/"}" ]] || fail canonical_commit_path_mismatch
printf 'CANONICAL_FIX=PASS commit=%s sha256=%s scope=one_controller_file\n' "$FIX_COMMIT" "$APPROVED_SHA"

# Refuse path substitution and retain the existing service sandbox/secret
# wrapper. Atomic replacement is limited to this one reviewed executable.
[[ -d "$(dirname "$LIVE")" && ! -L "$(dirname "$LIVE")" ]] || fail unsafe_live_directory
if [[ -e "$LIVE" ]]; then
  [[ -f "$LIVE" && ! -L "$LIVE" ]] || fail unsafe_live_controller_path
  [[ "$(stat -c '%U:%G:%a' "$LIVE")" == root:root:755 ]] || fail live_controller_protection_mismatch
fi
if [[ ! -e "$LIVE" || "$(sha "$LIVE")" != "$APPROVED_SHA" ]]; then
  temporary=$(mktemp "$(dirname "$LIVE")/.lifeos-powerdown.${JOB_ID}.XXXXXX")
  trap 'rm -f "${temporary:-}"' EXIT
  install -o root -g root -m 0755 "$SOURCE" "$temporary"
  [[ "$(sha "$temporary")" == "$APPROVED_SHA" ]] || fail staged_controller_hash_mismatch
  mv -f "$temporary" "$LIVE"
  trap - EXIT
  printf 'DEPLOYED=%s\n' "$LIVE"
else
  printf 'ALREADY_CURRENT=%s\n' "$LIVE"
fi
[[ "$(sha "$LIVE")" == "$APPROVED_SHA" ]] || fail live_controller_hash_mismatch
[[ "$(stat -c '%U:%G:%a' "$LIVE")" == root:root:755 ]] || fail live_controller_post_install_protection
printf 'PROTECTED_DEPLOYMENT=PASS owner=root:root mode=0755\n'

# It is now after the event. These runs cannot release reserve and exist only
# to verify the deployed controller and settle current fail-closed state.
run 90s systemctl start --wait "$SERVICE" || fail controller_run_one_failed
run 90s systemctl start --wait "$SERVICE" || fail controller_run_two_failed
[[ -r "$STATUS" && -r "$EVIDENCE" ]] || fail status_or_event_evidence_missing

run 30s python3 - "$SOURCE" "$STATUS" "$EVIDENCE" <<'PY' || fail event_5833_runtime_proof_incomplete
import ast
import datetime as dt
import json
import sys

source_path, status_path, evidence_path = sys.argv[1:]
tree = ast.parse(open(source_path).read(), source_path)
constants = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        try:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
        except Exception:
            pass
expected = {
    "MAX_SOURCE_AGE": 150,
    "MAX_SOURCE_TIMESTAMP_DELTA": 90,
    "MAX_GRID_DIFF_W": 100,
    "CROSSCHECK_REQUIRED_GOOD_RUNS": 2,
}
assert all(constants.get(k) == v for k, v in expected.items()), (constants, expected)

status = json.load(open(status_path))
rows = []
with open(evidence_path) as stream:
    for number, line in enumerate(stream, 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"invalid evidence line {number}: {exc}")

def event_id(value):
    return str(value) if value is not None else ""

def timestamp(row):
    value = row.get("recorded_at") or row.get("generated_at")
    return dt.datetime.fromisoformat(value) if value else None

start = dt.datetime.fromisoformat("2026-09-01T18:00:00+01:00")
end = dt.datetime.fromisoformat("2026-09-01T19:00:00+01:00")
bad = {"authoritative_grid_stale", "aligned_crosscheck_unavailable"}
pre, active, restored = [], [], []
for index, row in enumerate(rows):
    event = row.get("event") or {}
    nxt = event.get("next_event") or {}
    reserve = row.get("reserve") or {}
    control = row.get("control") or {}
    telemetry = row.get("telemetry") or {}
    cross = telemetry.get("crosscheck") or {}
    flags = set(row.get("anomaly_flags") or [])
    when = timestamp(row)
    if (when and when < start and not event.get("active")
            and event_id(nxt.get("id")) == "5833"
            and str(nxt.get("start", "")).startswith("2026-09-01T18:00:00")
            and str(nxt.get("end", "")).startswith("2026-09-01T19:00:00")
            and (row.get("readiness") or {}).get("state") == "READY"
            and telemetry.get("crosscheck_pass") is True
            and cross.get("current_good") is True and cross.get("trusted") is True
            and int(cross.get("good_runs", 0)) >= 2 and not flags & bad
            and reserve.get("controller_owns_reserve") is False
            and reserve.get("saved_pre_event_percent") is None
            and control.get("write_performed") is False):
        pre.append((index, row))
    if (when and start <= when < end and event.get("active") is True
            and event_id(event.get("id")) == "5833"
            and telemetry.get("crosscheck_pass") is True
            and cross.get("current_good") is True and cross.get("trusted") is True
            and not flags & bad and reserve.get("saved_pre_event_percent") is not None
            and reserve.get("controller_owns_reserve") is True
            and control.get("action") == "ACTIVE_EVENT_RESERVE_RELEASE"
            and control.get("write_performed") is True):
        active.append((index, row))
    if (when and when >= end and control.get("action") == "POST_EVENT_RESERVE_RESTORE"
            and control.get("write_performed") is True
            and reserve.get("restored_this_run") is True
            and reserve.get("controller_owns_reserve") is False):
        restored.append((index, row))

assert pre, "missing pre-event READY/trusted/no-write proof for event 5833"
assert active, "missing gated active-event release/ownership proof for event 5833"
assert restored, "missing post-event restoration proof for event 5833"
assert pre[-1][0] < active[0][0] < restored[-1][0], "event proof is not ordered"
saved = float((active[0][1].get("reserve") or {})["saved_pre_event_percent"])
final_reserve = status.get("reserve") or {}
final_control = status.get("control") or {}
assert final_reserve.get("controller_owns_reserve") is False, final_reserve
assert final_reserve.get("saved_pre_event_percent") is None, final_reserve
assert final_control.get("action") == "NO_WRITE_OUTSIDE_EVENT", final_control
assert final_control.get("write_performed") is False, final_control
assert abs(float(final_reserve["current_percent"]) - saved) <= 0.5
print("FAIL_CLOSED_CONSTANTS=PASS")
print(f"EVENT_5833_PRE_EVENT_PROOF=PASS rows={len(pre)}")
print(f"EVENT_5833_ACTIVE_PROOF=PASS rows={len(active)}")
print(f"EVENT_5833_RESTORE_PROOF=PASS rows={len(restored)}")
print(f"RESERVE_RESTORED=PASS saved={saved} current={final_reserve['current_percent']}")
print("CONTROLLER_OWNERSHIP_CLEARED=PASS")
PY

printf '%s\n' \
  'ISSUE_VALIDITY=ALREADY_COMPLETE' \
  'LIFEOS_WORK_STATE=PASS' \
  'BARRIER=none' \
  'NEXT_AUTONOMOUS_ACTION=close issue 25 with the redacted Watchman proof output' \
  'DISCOVERED_ISSUES_JSON_B64=none' \
  'RESULT=PASS' \
  'TESTS=canonical scope/hash/syntax, protected deployment, two post-event runs, ordered event 5833 evidence, restoration and ownership clearing PASS' \
  'NEXT_RUNTIME_CHECK=none'
