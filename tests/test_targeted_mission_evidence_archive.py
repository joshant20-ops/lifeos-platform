import json
import os
from pathlib import Path
import subprocess


EXPORTER = Path("governor/scripts/export-lifeos-job-records.sh").read_text()
WORKFLOW = Path(".github/workflows/lifeos-pa-mission-control.yml").read_text()


def test_exporter_supports_exact_job_filter_and_redacts_local_only_request():
    assert "LIFEOS_JOB_ID_FILTER" in EXPORTER
    assert "if job_filter and str(job.get('id') or '') != job_filter" in EXPORTER
    assert 'raise SystemExit("requested_job_record_not_found")' in EXPORTER
    assert "[LOCAL-ONLY REQUEST REDACTED]" in EXPORTER
    assert 'fetch origin refs/heads/main' in EXPORTER
    assert 'REMOTE_MAIN=$(git -C "$JOBS_REPO" rev-parse FETCH_HEAD)' in EXPORTER
    assert 'worktree add --detach "$EXPORT_WORKTREE" "$REMOTE_MAIN"' in EXPORTER
    assert 'ls-remote origin refs/heads/main' in EXPORTER
    assert 'push origin HEAD:main' in EXPORTER


def test_targeted_mission_requires_durable_pass_record_before_archive_pass():
    archive = WORKFLOW.split("- name: Verify archived disposition evidence", 1)[1]
    archive = archive.split("- name: Surface consolidated bundle", 1)[0]
    assert 'LIFEOS_JOB_ID_FILTER="$job_id" bash governor/scripts/export-lifeos-job-records.sh' in archive
    assert 'remote_main=$(git -C /home/joshan/lifeos-jobs rev-parse FETCH_HEAD)' in archive
    assert 'show", f"{remote_main}:jobs/{job_id}.json"' in archive
    assert 'assert record["status"] == "PASS"' in archive
    assert 'assert record["iterations"][0]["verdict"] == "PASS"' in archive
    assert 'assert record["request"] == "[LOCAL-ONLY REQUEST REDACTED]"' in archive
    assert 'cat-file -e "$remote_main:jobs/$job_id.json"' in archive
    assert 'echo "ARCHIVED_JOB_RECORD=$job_id"' in archive


def _git(*args, cwd=None):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_targeted_export_ignores_stale_local_history_and_publishes_redacted_record(tmp_path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    state = tmp_path / "state"
    state.mkdir()

    _git("init", "--bare", "--initial-branch=main", str(remote))
    _git("clone", str(remote), str(seed))
    _git("config", "user.name", "test", cwd=seed)
    _git("config", "user.email", "test@example.invalid", cwd=seed)
    (seed / "jobs").mkdir()
    (seed / "README.md").write_text("evidence\n")
    _git("add", ".", cwd=seed)
    _git("commit", "-m", "initial", cwd=seed)
    _git("push", "origin", "main", cwd=seed)
    _git("clone", str(remote), str(checkout))
    _git("config", "user.name", "test", cwd=checkout)
    _git("config", "user.email", "test@example.invalid", cwd=checkout)

    # Reproduce the live runner's nonstandard fetch behaviour: a plain
    # `git fetch origin main` updates FETCH_HEAD but leaves origin/main stale.
    _git("config", "--unset-all", "remote.origin.fetch", cwd=checkout)
    (seed / "REMOTE_ADVANCED.md").write_text("new remote state\n")
    _git("add", "REMOTE_ADVANCED.md", cwd=seed)
    _git("commit", "-m", "advance remote after checkout", cwd=seed)
    _git("push", "origin", "main", cwd=seed)

    # Reproduce the live failure: the persistent checkout is clean but ahead
    # with a stale, unredacted job record that must never be pushed.
    (checkout / "jobs").mkdir()
    stale = checkout / "jobs" / "stale.json"
    stale.write_text('{"request":"PRIVATE STALE CONTENT"}\n')
    _git("add", "jobs/stale.json", cwd=checkout)
    _git("commit", "-m", "stale local history", cwd=checkout)

    job_id = "job123"
    (state / f"{job_id}.json").write_text(json.dumps({
        "id": job_id,
        "request": "PRIVATE REQUEST",
        "privacy": "local-only",
        "created_at": "2026-09-22T00:00:00Z",
        "started_at": "2026-09-22T00:00:01Z",
        "completed_at": "2026-09-22T00:00:02Z",
        "status": "PASS",
        "stage": "complete",
        "iterations": [{
            "iteration": 1,
            "verification": {"verdict": "PASS", "reason": "verified"},
        }],
    }))

    env = os.environ | {
        "LIFEOS_AGENT_STATE": str(state),
        "LIFEOS_JOBS_REPO": str(checkout),
        "LIFEOS_JOB_ID_FILTER": job_id,
    }
    result = subprocess.run(
        ["bash", "governor/scripts/export-lifeos-job-records.sh"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "RESULT=PASS" in result.stdout
    assert "JOBS_EXPORT=updated" in result.stdout
    exported = json.loads(_git("show", f"origin/main:jobs/{job_id}.json", cwd=checkout))
    assert exported["request"] == "[LOCAL-ONLY REQUEST REDACTED]"
    assert exported["status"] == "PASS"
    assert exported["iterations"][0]["verdict"] == "PASS"
    remote_files = _git("ls-tree", "-r", "--name-only", "origin/main", cwd=checkout).splitlines()
    assert "jobs/stale.json" not in remote_files
    assert _git("status", "--porcelain", cwd=checkout) == ""
    assert _git("log", "-1", "--format=%s", cwd=checkout) == "stale local history"


def test_targeted_export_fails_when_requested_state_record_is_missing(tmp_path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    state = tmp_path / "state"
    state.mkdir()

    _git("init", "--bare", "--initial-branch=main", str(remote))
    _git("clone", str(remote), str(seed))
    _git("config", "user.name", "test", cwd=seed)
    _git("config", "user.email", "test@example.invalid", cwd=seed)
    (seed / "README.md").write_text("evidence\n")
    _git("add", ".", cwd=seed)
    _git("commit", "-m", "initial", cwd=seed)
    _git("push", "origin", "main", cwd=seed)
    _git("clone", str(remote), str(checkout))

    result = subprocess.run(
        ["bash", "governor/scripts/export-lifeos-job-records.sh"],
        capture_output=True,
        text=True,
        env=os.environ | {
            "LIFEOS_AGENT_STATE": str(state),
            "LIFEOS_JOBS_REPO": str(checkout),
            "LIFEOS_JOB_ID_FILTER": "missing-job",
        },
    )

    assert result.returncode != 0
    assert "requested_job_record_not_found" in result.stderr


def test_targeted_issue_runner_requires_explicit_objective_for_non_benchmark():
    runner = (ROOT / "governor/scripts/lifeos-pa-mission").read_text()
    assert 'LIFEOS_PA_TARGET_OBJECTIVE' in runner
    assert 'TARGET_OBJECTIVE_MISSING' in runner
    assert 'if target == "759" and not objective:' in runner
    assert 'TARGETED_ISSUE_ACCEPTANCE=PASS' in runner


def test_mission_control_accepts_generic_target_issue_inputs():
    workflow = (ROOT / ".github/workflows/lifeos-pa-mission-control.yml").read_text()
    assert "target_issue:" in workflow
    assert "target_objective:" in workflow
    assert "canonical_assertions:" in workflow
    assert "LIFEOS_PA_TARGET_OBJECTIVE:" in workflow
    assert "TARGETED_ISSUE_ACCEPTANCE=PASS" in workflow
    assert "ISSUE_DISPOSITIONS=#$target_issue ready_for_evidence_backed_closure" in workflow


def test_archive_accepts_bounded_governor_iterations():
    workflow = (ROOT / ".github/workflows/lifeos-pa-mission-control.yml").read_text()
    assert 'iterations = record.get("iterations") or []' in workflow
    assert 'assert iterations[-1]["verdict"] == "PASS"' in workflow
    assert 'len(record["iterations"]) == 1' not in workflow
