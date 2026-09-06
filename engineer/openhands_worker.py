#!/usr/bin/env python3
"""Dry-run-first OpenHands adapter using the Pi5 Governor AI broker.

OpenHands remains an execution agent on Engineer/Z97. It never receives cloud
provider credentials; it receives only a bounded broker token and endpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from provider_router import load_policy

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    ).stdout.strip()


def packet(task_file, repo, maximum=16000):
    task = task_file.read_text(encoding="utf-8")
    if len(task.encode()) > maximum:
        raise ValueError("task packet exceeds compact context limit")
    return json.dumps(
        {
            "task": task,
            "repository": repo.name,
            "head": git(repo, "rev-parse", "HEAD"),
            "branch": git(repo, "branch", "--show-current"),
            "status": git(repo, "status", "--short")[:4000],
            "constraints": [
                "branch/PR only",
                "no production SSH mutation",
                "Pi execution via relay",
                "AI inference must pass through Pi5 Governor broker",
                "private/local-only jobs must never cloud-fallback",
            ],
        },
        sort_keys=True,
    )


def broker_environment(path: Path, privacy: str) -> dict[str, str]:
    if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RuntimeError("broker config must be regular non-symlink mode-0600")
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and value and name in {"LIFEOS_GOVERNOR_BROKER_URL", "LIFEOS_GOVERNOR_BROKER_TOKEN"}:
            values[name] = value
    url = values.get("LIFEOS_GOVERNOR_BROKER_URL", "")
    token = values.get("LIFEOS_GOVERNOR_BROKER_TOKEN", "")
    if not url.startswith("http://") and not url.startswith("https://"):
        raise RuntimeError("broker URL unavailable")
    if not token:
        raise RuntimeError("broker token unavailable")
    model = "openai/lifeos-local-only" if privacy == "local-only" else "openai/lifeos-normal"
    return {
        "LIFEOS_PROVIDER": "governor-broker",
        "LLM_MODEL": model,
        "LLM_BASE_URL": url.rstrip("/"),
        "LLM_API_KEY": token,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--task", type=Path, required=True)
    p.add_argument(
        "--task-class",
        choices=("deterministic", "tiny", "offline", "normal", "substantial", "review", "escalation"),
        default="normal",
    )
    p.add_argument("--privacy", choices=("normal", "local-only"), default="normal")
    p.add_argument("--secrets", type=Path, help="deprecated; provider secrets are Pi5-only")
    p.add_argument(
        "--broker-config",
        type=Path,
        default=Path.home() / ".config/lifeos/governor-broker.env",
    )
    p.add_argument("--execute", action="store_true")
    p.add_argument("--openhands-command", default="openhands")
    a = p.parse_args()
    evidence = {
        "schema_version": 3,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": not a.execute,
        "privacy": a.privacy,
        "inference_authority": "pi5-governor",
    }
    try:
        branch = git(a.repo, "branch", "--show-current")
        if not branch or branch in {"main", "master"}:
            raise RuntimeError("controlled non-main branch required")
        before = git(a.repo, "rev-parse", "refs/heads/main")
        context = packet(a.task, a.repo)
        policy = load_policy(ROOT / "governor/policy.json")
        broker_env = broker_environment(a.broker_config, a.privacy)
        evidence.update(
            max_attempts=policy["routing"]["max_attempts_per_provider"],
            branch=branch,
            main_before=before,
            context_sha256=hashlib.sha256(context.encode()).hexdigest(),
            selected_provider="governor-broker",
            selected_role="inference-policy-authority",
            attempts=[],
        )
        if not a.execute:
            evidence["result"] = "DRY_RUN_PASS"
            print(json.dumps(evidence, sort_keys=True))
            return 0

        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            **broker_env,
        }
        max_attempts = int(policy["routing"].get("max_attempts_per_provider", 1))
        for attempt in range(1, max_attempts + 1):
            done = subprocess.run(
                [
                    a.openhands_command,
                    "--headless",
                    "--override-with-envs",
                    "-t",
                    context,
                ],
                cwd=a.repo,
                env=env,
                timeout=1800,
                check=False,
            )
            evidence["attempts"].append(
                {"provider": "governor-broker", "attempt": attempt, "exit_code": done.returncode}
            )
            after = git(a.repo, "rev-parse", "refs/heads/main")
            if before != after:
                evidence.update(
                    main_after=after,
                    concurrent_main_unchanged=False,
                    result="FAIL_CLOSED",
                )
                print(json.dumps(evidence, sort_keys=True))
                return 1
            if done.returncode == 0:
                evidence.update(
                    main_after=after,
                    concurrent_main_unchanged=True,
                    result="PASS",
                )
                print(json.dumps(evidence, sort_keys=True))
                return 0

        evidence.update(main_after=before, concurrent_main_unchanged=True, result="BROKER_EXECUTION_EXHAUSTED")
        print(json.dumps(evidence, sort_keys=True))
        return 21
    except Exception as exc:
        evidence.update(result="FAIL_CLOSED", error_class=type(exc).__name__, error=str(exc)[:300])
        print(json.dumps(evidence, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
