#!/usr/bin/env python3
"""Claim queued LifeOS jobs and run bounded OpenHands engineering drafts.

This worker consumes the *same* governor state queue populated by GitHub intake.
It never deploys to the Pi, never merges, and never pushes. Successful drafts
stop in awaiting_review only after deterministic acceptance commands pass and
reviewable workspace changes are present.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from governor import DEFAULT_CONFIG, DEFAULT_STATE_DIR, Governor, Job, atomic_json, compact_packet, load_json, now

ROOT = Path(__file__).resolve().parent
DEFAULT_REPO = Path(os.environ.get("LIFEOS_ENGINEER_REPO", "/home/joshan/workspace/lifeos-platform"))
DEFAULT_ADAPTER = ROOT / "adapters" / "openhands.sh"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def queue_dirs(state_dir: Path) -> dict[str, Path]:
    root = state_dir / "queue"
    names = ("pending", "running", "awaiting_review", "blocked", "failed", "evidence", "attempts", "context", "worktrees")
    result = {name: root / name for name in names}
    for path in result.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return result


def valid_job(data: dict[str, Any]) -> Job:
    required = ("id", "task", "risk", "base_commit", "acceptance_commands")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError("missing job fields: " + ", ".join(missing))
    job_id = str(data["id"])
    if not SAFE_ID.fullmatch(job_id):
        raise ValueError("unsafe job id")
    if not re.fullmatch(r"[0-9a-f]{40}", str(data["base_commit"])):
        raise ValueError("invalid base commit")
    commands = data.get("acceptance_commands")
    if not isinstance(commands, list) or not commands or not all(isinstance(x, str) and x.strip() for x in commands):
        raise ValueError("acceptance_commands must be a non-empty string list")
    return Job(
        id=job_id,
        task=str(data["task"]),
        risk=str(data.get("risk", "NORMAL")),
        deterministic_available=bool(data.get("deterministic_available", False)),
        substantial=bool(data.get("substantial", True)),
        requires_review=bool(data.get("requires_review", True)),
        base_commit=str(data["base_commit"]),
        allow_offline_fallback=bool(data.get("allow_offline_fallback", False)),
    )


def claim_one(paths: dict[str, Path]) -> Path | None:
    for pending in sorted(paths["pending"].glob("*.json")):
        running = paths["running"] / pending.name
        try:
            pending.replace(running)
            return running
        except FileNotFoundError:
            continue
    return None


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=check)


def ensure_base(repo: Path, base_commit: str) -> None:
    current = git(repo, "rev-parse", "HEAD").stdout.strip()
    if current != base_commit:
        raise RuntimeError(f"checkout HEAD {current} no longer equals job base {base_commit}")
    if git(repo, "status", "--porcelain").stdout.strip():
        raise RuntimeError("engineer source checkout is dirty")


def worktree_for(repo: Path, paths: dict[str, Path], job: Job) -> Path:
    worktree = paths["worktrees"] / job.id
    branch = "engineer/" + job.id[:80]
    if worktree.exists():
        head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        if head != job.base_commit:
            raise RuntimeError("existing job worktree has unexpected HEAD")
        return worktree
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree), job.base_commit],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree), branch],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError("unable to create job worktree: " + result.stderr.strip())
    return worktree


def provider_environment(governor: Governor, decision: dict[str, Any], context_path: Path) -> dict[str, str]:
    name = str(decision["provider"])
    provider = governor.config["providers"][name]
    if provider.get("kind") != "openai_compatible":
        raise RuntimeError(f"provider {name} cannot be executed by the OpenHands adapter")
    base_url = provider.get("base_url")
    if not base_url and provider.get("base_url_template"):
        values = {key: os.environ.get(key, "") for key in provider.get("credential_env", [])}
        base_url = str(provider["base_url_template"]).format(**values)
    credentials = provider.get("credential_env", [])
    api_key = "ollama-local-no-secret"
    if credentials:
        key_name = credentials[0]
        api_key = os.environ.get(key_name, "")
        if not api_key:
            raise RuntimeError(f"credential {key_name} unavailable")
    env = os.environ.copy()
    env.update({
        "LIFEOS_SELECTED_BASE_URL": str(base_url),
        "LIFEOS_SELECTED_MODEL": str(decision["model"]),
        "LIFEOS_SELECTED_API_KEY": api_key,
        "LIFEOS_CONTEXT_PACKET": str(context_path),
    })
    return env


def acceptance(worktree: Path, commands: list[str], timeout: int) -> list[dict[str, Any]]:
    results = []
    for command in commands:
        completed = subprocess.run(
            ["/bin/sh", "-lc", command], cwd=worktree, text=True,
            capture_output=True, timeout=timeout, check=False,
        )
        results.append({
            "command": command,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        })
        if completed.returncode != 0:
            break
    return results


def reviewable_changes(worktree: Path) -> list[str]:
    """Return changed paths that make an implementation draft reviewable."""
    lines = git(worktree, "status", "--porcelain").stdout.splitlines()
    return [line[3:] if len(line) > 3 else line for line in lines if line.strip()]


def move(path: Path, destination: Path) -> Path:
    target = destination / path.name
    path.replace(target)
    return target


def attempts_for(paths: dict[str, Path], job_id: str) -> int:
    return int(load_json(paths["attempts"] / f"{job_id}.json", {}).get("attempts", 0))


def record_attempt(paths: dict[str, Path], job_id: str, count: int, status: str) -> None:
    atomic_json(paths["attempts"] / f"{job_id}.json", {"job_id": job_id, "attempts": count, "status": status, "updated_at": now()})


def process_one(governor: Governor, state_dir: Path, repo: Path, adapter: Path,
                execute: bool, agent_timeout: int, command_timeout: int) -> dict[str, Any]:
    paths = queue_dirs(state_dir)
    claimed = claim_one(paths)
    if not claimed:
        return {"status": "IDLE", "generated_at": now()}
    data = load_json(claimed, {})
    try:
        job = valid_job(data)
        ensure_base(repo, str(job.base_commit))
        decision = governor.route(job)
        evidence: dict[str, Any] = {"job_id": job.id, "started_at": now(), "route": decision, "execute": execute}
        if decision.get("status") == "GATED":
            evidence["status"] = "BLOCKED_GOVERNOR_GATE"
            atomic_json(paths["evidence"] / f"{job.id}.json", evidence)
            move(claimed, paths["blocked"])
            return evidence
        if decision.get("status") != "ROUTED":
            evidence["status"] = str(decision.get("status"))
            atomic_json(paths["evidence"] / f"{job.id}.json", evidence)
            move(claimed, paths["pending"])
            return evidence
        if decision.get("provider") == "deterministic":
            evidence["status"] = "BLOCKED_DETERMINISTIC_TASK_NEEDS_EXPLICIT_RUNNER"
            atomic_json(paths["evidence"] / f"{job.id}.json", evidence)
            move(claimed, paths["blocked"])
            return evidence
        if not execute:
            evidence["status"] = "ROUTED_DRY_RUN"
            atomic_json(paths["evidence"] / f"{job.id}.json", evidence)
            move(claimed, paths["pending"])
            return evidence

        worktree = worktree_for(repo, paths, job)
        context_files = [worktree / item for item in data.get("context_paths", []) if isinstance(item, str)]
        packet = compact_packet(context_files, 65536)
        packet["job"] = data
        packet["instructions"] = [
            "Work only in this job worktree.",
            "Do not deploy to the Pi, merge, push, delete production data, or expose secrets.",
            "Implement the GitHub issue, run deterministic tests, and leave reviewable workspace changes.",
        ]
        context_path = paths["context"] / f"{job.id}.json"
        atomic_json(context_path, packet)
        env = provider_environment(governor, decision, context_path)
        env["LIFEOS_JOB_TASK"] = job.task
        completed = subprocess.run(
            [str(adapter)], cwd=worktree, env=env, text=True,
            capture_output=True, timeout=agent_timeout, check=False,
        )
        evidence["agent_returncode"] = completed.returncode
        evidence["agent_stdout_tail"] = completed.stdout[-8000:]
        evidence["agent_stderr_tail"] = completed.stderr[-8000:]
        if completed.returncode != 0:
            raise RuntimeError(f"OpenHands exited {completed.returncode}")
        checks = acceptance(worktree, list(data["acceptance_commands"]), command_timeout)
        evidence["acceptance"] = checks
        if not checks or any(item["returncode"] != 0 for item in checks):
            raise RuntimeError("deterministic acceptance command failed")
        evidence["diff_check"] = git(worktree, "diff", "--check", check=False).returncode
        if evidence["diff_check"] != 0:
            raise RuntimeError("git diff --check failed")
        changed_paths = reviewable_changes(worktree)
        evidence["changed_paths"] = changed_paths
        evidence["changed_path_count"] = len(changed_paths)
        if not changed_paths:
            raise RuntimeError("OpenHands produced no reviewable workspace changes")
        evidence["status"] = "AWAITING_REVIEW"
        evidence["finished_at"] = now()
        evidence["worktree"] = str(worktree)
        atomic_json(paths["evidence"] / f"{job.id}.json", evidence)
        governor.record(str(decision["provider"]), "SUCCESS", job.id)
        move(claimed, paths["awaiting_review"])
        record_attempt(paths, job.id, attempts_for(paths, job.id) + 1, "AWAITING_REVIEW")
        return evidence
    except Exception as exc:
        job_id = str(data.get("id") or claimed.stem)
        count = attempts_for(paths, job_id) + 1
        max_retries = int(governor.config.get("policy", {}).get("max_retries", 2))
        evidence = {"job_id": job_id, "status": "FAILED_ATTEMPT", "error": str(exc), "attempt": count, "generated_at": now()}
        atomic_json(paths["evidence"] / f"{job_id}.json", evidence)
        record_attempt(paths, job_id, count, "FAILED_ATTEMPT")
        provider = None
        try:
            provider = decision.get("provider")  # type: ignore[name-defined]
        except Exception:
            pass
        if provider in governor.config.get("providers", {}):
            governor.record(str(provider), "FAILURE", job_id)
        if count <= max_retries:
            move(claimed, paths["pending"])
            evidence["retry"] = True
        else:
            move(claimed, paths["failed"])
            evidence["retry"] = False
        return evidence


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Consume one queued LifeOS AI governor job")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    p.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    p.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    p.add_argument("--execute", action="store_true", help="actually invoke OpenHands; otherwise route-only dry run")
    p.add_argument("--agent-timeout", type=int, default=1800)
    p.add_argument("--command-timeout", type=int, default=300)
    return p


def main() -> int:
    args = parser().parse_args()
    governor = Governor(args.config, args.state_dir)
    result = process_one(governor, args.state_dir, args.repo, args.adapter, args.execute, args.agent_timeout, args.command_timeout)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") not in {"FAILED_ATTEMPT"} else 1


if __name__ == "__main__":
    sys.exit(main())
