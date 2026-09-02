#!/usr/bin/env bash
set -Eeuo pipefail

# Post-event closure for issue #25.  The dated event cannot safely be replayed:
# reuse the already-reviewed bounded control-broker deployment, then validate
# the append-only evidence produced during the real event.
readonly PLATFORM=/home/joshan/lifeos-platform
readonly DEPLOYER="$PLATFORM/governor/runtime_jobs/16101567d458.sh"
readonly SOURCE="$PLATFORM/homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
readonly LIVE=/usr/local/sbin/lifeos-powerdown-assurance-active
readonly STATUS=/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json
readonly EVIDENCE=/opt/lifeos-watch/octopus-powerdown-assurance/event-evidence-v52.jsonl
readonly FIX_COMMIT=6968eb4ea119f371a49960630cc7a4e62a094943
readonly APPROVED_SHA=fd7b1ce6e89bfd195fd86cb03a39f3c0ad592dc04d2091232f027f28375e23e7

run() { local limit=$1; shift; timeout --signal=TERM --kill-after=10s "$limit" "$@"; }
sha() { sha256sum "$1" | awk '{print $1}'; }
finish() {
  local result=$1 state=$2 barrier=$3 tests=$4 next=$5 validity=${6:-VALID}
  printf '%s\n' \
    "ISSUE_VALIDITY=$validity" \
    "LIFEOS_WORK_STATE=$state" \
    "BARRIER=$barrier" \
    "NEXT_AUTONOMOUS_ACTION=$next" \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    "RESULT=$result" \
    "TESTS=$tests" \
    "NEXT_RUNTIME_CHECK=$next"
  [[ "$result" == PASS ]]
}
trap 'rc=$?; if ((rc)); then finish RETRY BLOCKED runtime_verification_failed "runtime acceptance failed; inspect the first FAIL/assertion" "rerun this launcher through Watchman after correcting the named failure"; fi' EXIT

[[ "$(hostname)" == Docker ]] || { echo 'FAIL=must_run_on_pi5_Docker'; exit 1; }
[[ -d "$PLATFORM/.git" ]] || { echo 'FAIL=canonical_repository_missing'; exit 1; }
head=$(git -C "$PLATFORM" rev-parse HEAD)
[[ "$head" == "$(git -C "$PLATFORM" rev-parse main)" ]] || { echo 'FAIL=canonical_head_not_main'; exit 1; }
[[ "$head" == "$(git -C "$PLATFORM" rev-parse refs/remotes/origin/main)" ]] || { echo 'FAIL=canonical_main_not_published'; exit 1; }
git -C "$PLATFORM" merge-base --is-ancestor "$FIX_COMMIT" "$head" || { echo 'FAIL=canonical_fix_missing'; exit 1; }
[[ "$(sha "$SOURCE")" == "$APPROVED_SHA" ]] || { echo 'FAIL=canonical_hash_mismatch'; exit 1; }
run 20s python3 -m py_compile "$SOURCE"
printf 'CANONICAL_FIX=PASS commit=%s sha256=%s\n' "$FIX_COMMIT" "$APPROVED_SHA"

# This existing launcher submits a content-addressed job through the authorised
# Unix-socket root broker and explicitly wakes the bounded runner, so it does
# not rely solely on the failed legacy polling loop.
[[ -x "$DEPLOYER" ]] || { echo 'FAIL=authorised_bounded_deployer_missing'; exit 1; }
run 600s "$DEPLOYER"

[[ -f "$LIVE" && ! -L "$LIVE" ]] || { echo 'FAIL=live_controller_missing_or_symlink'; exit 1; }
[[ "$(sha "$LIVE")" == "$APPROVED_SHA" ]] || { echo 'FAIL=live_hash_mismatch'; exit 1; }
[[ "$(stat -c '%U:%G:%a' "$LIVE")" == root:root:755 ]] || { echo 'FAIL=live_protection_mismatch'; exit 1; }
[[ -r "$STATUS" && -r "$EVIDENCE" ]] || { echo 'FAIL=status_or_evidence_unreadable'; exit 1; }

run 30s python3 - "$SOURCE" "$STATUS" "$EVIDENCE" <<'PY'
import ast
import datetime as dt
import json
import sys

source_path, status_path, evidence_path = sys.argv[1:]

# Prove that deployment did not relax any named fail-closed constant.
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
    if (not event.get("active") and event_id(nxt.get("id")) == "5833"
            and str(nxt.get("start", "")).startswith("2026-09-01T18:00:00")
            and str(nxt.get("end", "")).startswith("2026-09-01T19:00:00")
            and (row.get("readiness") or {}).get("state") == "READY"
            and telemetry.get("crosscheck_pass") is True
            and cross.get("current_good") is True and cross.get("trusted") is True
            and int(cross.get("good_runs", 0)) >= 2 and not flags & bad
            and reserve.get("controller_owns_reserve") is False
            and reserve.get("saved_pre_event_percent") is None
            and control.get("write_performed") is False
            and when and when < dt.datetime.fromisoformat("2026-09-01T18:00:00+01:00")):
        pre.append((index, row))
    if (event.get("active") is True and event_id(event.get("id")) == "5833"
            and telemetry.get("crosscheck_pass") is True
            and cross.get("current_good") is True and cross.get("trusted") is True
            and not flags & bad and reserve.get("saved_pre_event_percent") is not None
            and reserve.get("controller_owns_reserve") is True
            and control.get("action") == "ACTIVE_EVENT_RESERVE_RELEASE"
            and when and dt.datetime.fromisoformat("2026-09-01T18:00:00+01:00") <= when
            < dt.datetime.fromisoformat("2026-09-01T19:00:00+01:00")):
        active.append((index, row))
    if (control.get("action") == "POST_EVENT_RESERVE_RESTORE"
            and control.get("write_performed") is True
            and reserve.get("restored_this_run") is True
            and reserve.get("controller_owns_reserve") is False
            and when and when >= dt.datetime.fromisoformat("2026-09-01T19:00:00+01:00")):
        restored.append((index, row))

assert pre, "missing pre-event READY/trusted/no-write proof for event 5833"
assert active, "missing gated active-event ownership/release proof for event 5833"
assert restored, "missing post-event reserve restoration proof for event 5833"
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

trap - EXIT
finish PASS PASS none \
  'canonical syntax/hash, brokered protected deployment, fail-closed constants, ordered event 5833 evidence, restoration and ownership clearing PASS' \
  none ALREADY_COMPLETE
