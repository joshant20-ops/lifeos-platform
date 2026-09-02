#!/usr/bin/env bash
set -Eeuo pipefail

# Watchman executes this bounded job on Pi5/Docker.  It deliberately does not
# use the legacy lifeos-pi-control incident queue, which was the blocker in the
# two earlier attempts for issue #25.
readonly JOB_ID=a4d9f522e8cd
readonly REPO=/home/joshan/lifeos-platform
readonly SOURCE="$REPO/homelab/live/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py"
readonly LIVE_EXEC=/usr/local/sbin/lifeos-powerdown-assurance-active
readonly LIVE_OPT=/opt/stacks/lifeos-energy/powerdown-assurance/lifeos-powerdown-assurance-active.py
readonly STATUS=/opt/lifeos-watch/octopus-powerdown-assurance/active-status.json
readonly EVIDENCE=/opt/lifeos-watch/octopus-powerdown-assurance/event-evidence-v52.jsonl
readonly SERVICE=lifeos-powerdown-assurance-active.service
readonly FIX_COMMIT=6968eb4ea119f371a49960630cc7a4e62a094943
readonly APPROVED_SHA=fd7b1ce6e89bfd195fd86cb03a39f3c0ad592dc04d2091232f027f28375e23e7

sha() { sha256sum "$1" | awk '{print $1}'; }
fail() {
  printf 'FAIL=%s\n' "$1"
  printf '%s\n' \
    'ISSUE_VALIDITY=VALID' \
    'LIFEOS_WORK_STATE=BLOCKED' \
    "BARRIER=$1" \
    'NEXT_AUTONOMOUS_ACTION=preserve fail-closed state and repair only the named runtime barrier through Watchman' \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    'RESULT=BLOCKED' \
    'TESTS=runtime acceptance failed' \
    "NEXT_RUNTIME_CHECK=$1"
  exit 1
}
run() { local limit=$1; shift; timeout --signal=TERM --kill-after=10s "$limit" "$@"; }

[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker
[[ "$(id -u)" -eq 0 ]] || fail must_run_as_root_via_Watchman
[[ -d "$REPO/.git" ]] || fail canonical_repository_missing
head=$(git -C "$REPO" rev-parse HEAD)
[[ "$head" == "$(git -C "$REPO" rev-parse main)" ]] || fail canonical_head_not_main
[[ "$head" == "$(git -C "$REPO" rev-parse refs/remotes/origin/main)" ]] || fail canonical_main_not_published
git -C "$REPO" merge-base --is-ancestor "$FIX_COMMIT" "$head" || fail canonical_fix_commit_missing
[[ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]] || fail canonical_repository_dirty
[[ -f "$SOURCE" && ! -L "$SOURCE" && "$(sha "$SOURCE")" == "$APPROVED_SHA" ]] || fail canonical_source_hash_mismatch
run 20s python3 -m py_compile "$SOURCE" || fail canonical_source_syntax
printf 'CANONICAL_FIX=PASS commit=%s sha256=%s\n' "$FIX_COMMIT" "$APPROVED_SHA"

install_exact() {
  local destination=$1 directory temporary
  directory=$(dirname "$destination")
  [[ -d "$directory" && ! -L "$directory" ]] || fail unsafe_live_directory
  if [[ -e "$destination" ]]; then
    [[ -f "$destination" && ! -L "$destination" ]] || fail unsafe_live_controller_path
    [[ "$(stat -c '%U:%G:%a' "$destination")" == root:root:755 ]] || fail live_controller_protection_mismatch
  fi
  if [[ ! -e "$destination" || "$(sha "$destination")" != "$APPROVED_SHA" ]]; then
    temporary=$(mktemp "$directory/.lifeos-powerdown.${JOB_ID}.XXXXXX")
    install -o root -g root -m 0755 "$SOURCE" "$temporary"
    [[ "$(sha "$temporary")" == "$APPROVED_SHA" ]] || fail staged_controller_hash_mismatch
    mv -f "$temporary" "$destination"
    printf 'DEPLOYED=%s\n' "$destination"
  else
    printf 'ALREADY_CURRENT=%s\n' "$destination"
  fi
  [[ "$(sha "$destination")" == "$APPROVED_SHA" ]] || fail live_controller_hash_mismatch
  [[ "$(stat -c '%U:%G:%a' "$destination")" == root:root:755 ]] || fail live_controller_post_install_protection
}

# Keep the service executable and its /opt canonical live copy identical.
install_exact "$LIVE_EXEC"
install_exact "$LIVE_OPT"
printf 'PROTECTED_DEPLOYMENT=PASS owner=root:root mode=0755\n'

# Retain the existing systemd secret wrapper and sandbox.  A post-event run is
# not permitted to release reserve; it can only complete a pending restoration
# or make the ordinary NO_WRITE_OUTSIDE_EVENT observation.
run 90s systemctl start --wait "$SERVICE" || fail controller_run_one_failed
run 90s systemctl start --wait "$SERVICE" || fail controller_run_two_failed
[[ -r "$STATUS" && -r "$EVIDENCE" ]] || fail status_or_event_evidence_missing

run 30s python3 - "$STATUS" "$EVIDENCE" <<'PY' || fail event_5833_runtime_proof_incomplete
import json, sys

status_path, evidence_path = sys.argv[1:]
status = json.load(open(status_path))
rows = []
with open(evidence_path) as stream:
    for number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid evidence JSON at line {number}: {exc}")

def event_id(value):
    return str(value) if value is not None else ""

bad_flags = {"authoritative_grid_stale", "aligned_crosscheck_unavailable"}
pre = []
active = []
restored = []
for index, row in enumerate(rows):
    event = row.get("event") or {}
    nxt = event.get("next_event") or {}
    reserve = row.get("reserve") or {}
    control = row.get("control") or {}
    telemetry = row.get("telemetry") or {}
    crosscheck = telemetry.get("crosscheck") or {}
    flags = set(row.get("anomaly_flags") or [])
    if (not event.get("active") and event_id(nxt.get("id")) == "5833" and
            str(nxt.get("start", "")).startswith("2026-09-01T18:00:00") and
            str(nxt.get("end", "")).startswith("2026-09-01T19:00:00") and
            (row.get("readiness") or {}).get("state") == "READY" and
            telemetry.get("crosscheck_pass") is True and
            crosscheck.get("current_good") is True and
            crosscheck.get("trusted") is True and
            int(crosscheck.get("good_runs", 0)) >= 2 and not (flags & bad_flags) and
            reserve.get("controller_owns_reserve") is False and
            control.get("write_performed") is False):
        pre.append((index, row))
    if (event.get("active") is True and event_id(event.get("id")) == "5833" and
            telemetry.get("crosscheck_pass") is True and
            crosscheck.get("current_good") is True and
            crosscheck.get("trusted") is True and not (flags & bad_flags) and
            reserve.get("saved_pre_event_percent") is not None and
            reserve.get("controller_owns_reserve") is True and
            control.get("action") == "ACTIVE_EVENT_RESERVE_RELEASE" and
            control.get("blocked_reason") is None):
        active.append((index, row))
    if (control.get("action") == "POST_EVENT_RESERVE_RESTORE" and
            control.get("write_performed") is True and
            reserve.get("restored_this_run") is True and
            reserve.get("controller_owns_reserve") is False):
        restored.append((index, row))

assert pre, "no safe pre-event evidence for event 5833"
assert active, "no gated active-event reserve-release evidence for event 5833"
assert restored, "no post-event reserve-restoration evidence"
assert pre[-1][0] < active[0][0] < restored[-1][0], "event evidence is out of order"

saved = float((active[0][1].get("reserve") or {})["saved_pre_event_percent"])
final_reserve = status.get("reserve") or {}
final_control = status.get("control") or {}
assert final_reserve.get("controller_owns_reserve") is False, "controller still owns reserve"
assert final_reserve.get("saved_pre_event_percent") is None, "saved reserve was not cleared"
assert final_control.get("write_performed") is False, "unexpected post-event write on final run"
assert final_control.get("action") == "NO_WRITE_OUTSIDE_EVENT", final_control
current = float(final_reserve["current_percent"])
assert abs(current - saved) <= 0.5, (saved, current)

print(f"EVENT_5833_PRE_EVENT_PROOF=PASS rows={len(pre)}")
print(f"EVENT_5833_ACTIVE_PROOF=PASS rows={len(active)}")
print(f"EVENT_5833_RESTORE_PROOF=PASS rows={len(restored)}")
print(f"RESERVE_RESTORED=PASS saved={saved} current={current}")
print("CONTROLLER_OWNERSHIP_CLEARED=PASS")
print("FAIL_CLOSED_GATES_PRESERVED=PASS")
PY

printf '%s\n' \
  'ISSUE_VALIDITY=ALREADY_COMPLETE' \
  'LIFEOS_WORK_STATE=PASS' \
  'BARRIER=none' \
  'NEXT_AUTONOMOUS_ACTION=close issue 25 with the redacted Watchman proof output' \
  'DISCOVERED_ISSUES_JSON_B64=none' \
  'RESULT=PASS' \
  'TESTS=canonical ancestry/hash/syntax, protected deployment, two sandboxed runs, ordered event 5833 evidence, restoration and ownership clearing PASS' \
  'NEXT_RUNTIME_CHECK=none'
