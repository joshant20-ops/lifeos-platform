#!/usr/bin/env python3
"""Dry-run-first OpenHands adapter; never publishes, merges, deploys, or uses SSH."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from provider_router import eligible_providers, load_policy, load_secret_names, openhands_environment
ROOT = Path(__file__).resolve().parents[1]

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20).stdout.strip()

def packet(task_file, repo, maximum=16000):
    task = task_file.read_text(encoding="utf-8")
    if len(task.encode()) > maximum: raise ValueError("task packet exceeds compact context limit")
    return json.dumps({"task": task, "repository": repo.name, "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "branch", "--show-current"), "status": git(repo, "status", "--short")[:4000],
        "constraints": ["branch/PR only", "no production SSH mutation", "zero spend", "Pi execution via relay"]}, sort_keys=True)

def main():
    p = argparse.ArgumentParser(); p.add_argument("--repo", type=Path, required=True); p.add_argument("--task", type=Path, required=True)
    p.add_argument("--task-class", choices=("deterministic", "tiny", "offline", "normal", "substantial", "review", "escalation"), default="normal")
    p.add_argument("--secrets", type=Path); p.add_argument("--execute", action="store_true"); p.add_argument("--openhands-command", default="openhands")
    a = p.parse_args(); evidence = {"schema_version": 1, "timestamp": datetime.now(timezone.utc).isoformat(), "dry_run": not a.execute}
    try:
        branch = git(a.repo, "branch", "--show-current")
        if not branch or branch in {"main", "master"}: raise RuntimeError("controlled non-main branch required")
        before = git(a.repo, "rev-parse", "refs/heads/main"); context = packet(a.task, a.repo)
        policy = load_policy(ROOT / "governor/policy.json")
        providers, considered = eligible_providers(policy, a.task_class, load_secret_names(a.secrets))
        evidence.update(considered=considered, max_attempts=policy["routing"]["max_attempts_per_provider"],
                        cooldown_seconds=policy["routing"]["cooldown_seconds"], branch=branch, main_before=before,
                        context_sha256=hashlib.sha256(context.encode()).hexdigest(), attempts=[])
        if not providers:
            evidence["result"] = "CREDENTIAL_REQUIRED" if any(x["status"] == "CREDENTIAL_REQUIRED" for x in considered) else "NO_PROVIDER"
            print(json.dumps(evidence, sort_keys=True)); return 20
        if not a.execute:
            evidence.update(selected_provider=providers[0]["id"], selected_role=providers[0]["role"], result="DRY_RUN_PASS")
            print(json.dumps(evidence, sort_keys=True)); return 0
        max_attempts = policy["routing"]["max_attempts_per_provider"]
        for provider in providers:
            if provider["role"] == "senior-review": raise RuntimeError("Codex is review-only")
            env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
                   **openhands_environment(provider, a.secrets)}
            for attempt in range(1, max_attempts + 1):
                done = subprocess.run([a.openhands_command, "--headless", "--task", context], cwd=a.repo,
                                      env=env, timeout=1800, check=False)
                evidence["attempts"].append({"provider": provider["id"], "attempt": attempt, "exit_code": done.returncode})
                after = git(a.repo, "rev-parse", "refs/heads/main")
                if before != after:
                    evidence.update(main_after=after, concurrent_main_unchanged=False, result="FAIL_CLOSED")
                    print(json.dumps(evidence, sort_keys=True)); return 1
                if done.returncode == 0:
                    evidence.update(selected_provider=provider["id"], selected_role=provider["role"], main_after=after,
                                    concurrent_main_unchanged=True, result="PASS")
                    print(json.dumps(evidence, sort_keys=True)); return 0
            evidence["attempts"][-1]["cooldown_seconds"] = policy["routing"]["cooldown_seconds"]
        evidence.update(main_after=before, concurrent_main_unchanged=True, result="PROVIDERS_EXHAUSTED")
        print(json.dumps(evidence, sort_keys=True)); return 21
    except Exception as exc:
        evidence.update(result="FAIL_CLOSED", error_class=type(exc).__name__, error=str(exc)[:300]); print(json.dumps(evidence, sort_keys=True)); return 1
if __name__ == "__main__": sys.exit(main())
