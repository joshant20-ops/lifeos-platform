"""Sanitised, deterministic Engineer job records suitable for Git publication."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
from typing import Any, Callable


RECORD_VERSION = 2
SENSITIVE_KEY = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|session|credential|private[_-]?key)"
)
ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|cookie|session|credential)\s*([:=])\s*([^\s,;]+)"
)
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
URL_CREDENTIALS = re.compile(r"(?i)(https?://[^\s/:@]+:)[^\s/@]+@")
PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?-----END [^-\n]*PRIVATE KEY-----",
    re.DOTALL,
)


def sanitise(value: Any, key: str = "") -> Any:
    """Redact secrets recursively; never accept environment or raw-log fields."""
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(k): sanitise(v, str(k))
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            if str(k).lower() not in {"environment", "environ", "raw_log", "raw_logs"}
        }
    if isinstance(value, (list, tuple)):
        return [sanitise(item) for item in value]
    if isinstance(value, str):
        value = PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", value)
        value = BEARER.sub("Bearer [REDACTED]", value)
        value = URL_CREDENTIALS.sub(r"\1[REDACTED]@", value)
        return ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", value)
    return value


def _summary(job: dict[str, Any]) -> str:
    request = " ".join(str(job.get("request") or "").split())
    return request[:500]


def _terminal_outcome(job: dict[str, Any], iterations: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose the authoritative reason an autonomous repair loop stopped."""
    status = str(job.get("status") or "UNKNOWN").upper()
    stage = str(job.get("stage") or "unknown")
    reason = str(job.get("blocked_reason") or job.get("failure_reason") or "")
    lowered = reason.lower()

    if status == "PASS":
        kind = "PASS"
        retry_allowed = False
    elif "repeated deterministic failure" in lowered or stage == "blocked_repeated_failure":
        kind = "REPEATED_FAILURE"
        retry_allowed = False
    elif "maximum iterations reached" in lowered:
        kind = "ITERATION_LIMIT"
        retry_allowed = False
    elif status == "BLOCKED":
        kind = "BLOCKED"
        retry_allowed = False
    else:
        kind = "NON_TERMINAL"
        retry_allowed = True

    last = iterations[-1] if iterations else {}
    return {
        "kind": kind,
        "terminal": kind != "NON_TERMINAL",
        "retry_allowed": retry_allowed,
        "reason": reason,
        "iteration_count": len(iterations),
        "last_failure_signature": (
            last.get("failure_signature") or job.get("last_failure_signature")
        ),
    }


def make_record(job: dict[str, Any], publication_state: str = "UNPUBLISHED") -> dict[str, Any]:
    """Convert mutable runtime state into the stable public record schema."""
    iterations = list(job.get("iterations") or [])
    last = iterations[-1] if iterations else {}
    evidence = str(last.get("evidence") or "")
    runtime_rc = None
    match = re.findall(r"(?m)^RUNTIME_RC=(\d+)\s*$", evidence)
    if match:
        runtime_rc = int(match[-1])
    record = {
        "record_version": RECORD_VERSION,
        "job_id": str(job.get("id") or ""),
        "goal_summary": _summary(job),
        "timestamps": {
            name: job.get(name)
            for name in ("created_at", "started_at", "completed_at", "stage_changed_at")
            if job.get(name)
        },
        "classification": str(job.get("privacy") or "unknown"),
        "stage": str(job.get("stage") or "unknown"),
        "final_status": str(job.get("status") or "UNKNOWN"),
        "iteration_count": len(iterations),
        "terminal_outcome": _terminal_outcome(job, iterations),
        "implementation_summary": job.get("implementation_summary") or "",
        "changed_files": sorted(set(job.get("changed_files") or [])),
        "canonical_commits": sorted(set(job.get("canonical_commits") or [])),
        "tests": job.get("tests") or {"count": 0, "summary": "not reported"},
        "runtime_artifact": job.get("runtime_artifact"),
        "runtime_return_code": runtime_rc if runtime_rc is not None else job.get("runtime_return_code"),
        "failure": {
            "class": job.get("failure_class"),
            "reason": job.get("blocked_reason") or job.get("failure_reason"),
        },
        "human_action_state": job.get("human_action_state") or "NONE",
        "next_runtime_check": job.get("next_runtime_check") or "none",
        "continuation": {
            "retry_of": job.get("retry_of"),
            "parent": job.get("continuation_parent"),
            "child": job.get("continuation_child"),
            "recovery_state": job.get("recovery_state") or "none",
        },
        "record_publication": {"state": publication_state},
    }
    return sanitise(record)


def serialise_record(record: dict[str, Any]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def publish_record(
    repo: pathlib.Path,
    job: dict[str, Any],
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Commit and push one record; leave a truthful local UNPUBLISHED record on failure."""
    job_id = str(job.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", job_id):
        return {"state": "UNPUBLISHED", "reason": "invalid_job_id"}
    path = repo / "governor" / "job_records" / f"{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialise_record(make_record(job, "PUBLISHED")))
    rel = str(path.relative_to(repo))

    def command(*args: str) -> subprocess.CompletedProcess[str]:
        return run(["git", *args], cwd=repo, text=True, capture_output=True, timeout=180)

    try:
        add = command("add", "--", rel)
        if add.returncode:
            raise RuntimeError("git_add_failed")
        diff = command("diff", "--cached", "--quiet", "--", rel)
        if diff.returncode == 1:
            commit = command("commit", "-m", f"agent: publish job record {job_id}", "--", rel)
            if commit.returncode:
                raise RuntimeError("git_commit_failed")
        elif diff.returncode != 0:
            raise RuntimeError("git_diff_failed")
        push = command("push", "origin", "HEAD:main")
        if push.returncode:
            raise RuntimeError("git_push_failed")
        head = command("rev-parse", "HEAD")
        return {"state": "PUBLISHED", "commit": head.stdout.strip() if head.returncode == 0 else None}
    except Exception as exc:
        # The working-tree copy is authoritative about failed publication. This
        # deliberately does not reset or discard a possibly valid local commit.
        path.write_text(serialise_record(make_record(job, "UNPUBLISHED")))
        return {"state": "UNPUBLISHED", "reason": str(exc)}
