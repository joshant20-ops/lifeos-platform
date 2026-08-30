#!/usr/bin/env python3
"""LifeOS provider-agnostic, zero-spend AI job governor."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "providers.json"
DEFAULT_STATE_DIR = Path(os.environ.get("LIFEOS_GOVERNOR_STATE_DIR", Path.home() / ".local/state/lifeos-ai-governor"))
RISKS = ("TINY", "NORMAL", "HIGH_RISK", "SENIOR_REVIEW")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


@dataclass
class Job:
    id: str
    task: str
    risk: str = "NORMAL"
    deterministic_available: bool = False
    substantial: bool = True
    requires_review: bool = True
    base_commit: str | None = None
    exclude_provider: str | None = None
    created_at: str = field(default_factory=now)


class Governor:
    def __init__(self, config_path: Path = DEFAULT_CONFIG, state_dir: Path = DEFAULT_STATE_DIR):
        self.config = load_json(config_path, {})
        self.state_dir = state_dir
        self.state_path = state_dir / "state.json"
        self.state = load_json(self.state_path, {"providers": {}, "daily_usage": {}})

    def _configured(self, provider: dict[str, Any]) -> bool:
        return all(os.environ.get(name) for name in provider.get("credential_env", []))

    def status(self, name: str, provider: dict[str, Any]) -> str:
        if provider.get("kind") == "deterministic":
            return "READY"
        if provider.get("auth") == "separate":
            return "AVAILABLE_SEPARATE_AUTH"
        if not self._configured(provider):
            return "CREDENTIAL_REQUIRED"
        if name == "ollama":
            try:
                with socket.create_connection(("127.0.0.1", 11434), timeout=0.2):
                    pass
            except OSError:
                return "UNREACHABLE"
        health = self.state.get("providers", {}).get(name, {})
        until = health.get("cooldown_until")
        if until and dt.datetime.fromisoformat(until) > dt.datetime.now(dt.timezone.utc):
            return "COOLDOWN"
        if health.get("failures", 0) >= self.config["policy"]["max_retries"]:
            return "RETRY_CAP_REACHED"
        return "READY"

    def health(self) -> list[dict[str, Any]]:
        result = []
        for name, provider in self.config["providers"].items():
            result.append({
                "provider": name,
                "status": self.status(name, provider),
                "model": os.environ.get(provider.get("model_env", ""), provider.get("model")),
                "failures": self.state.get("providers", {}).get(name, {}).get("failures", 0),
                "usage_today": self.state.get("daily_usage", {}).get(dt.date.today().isoformat(), {}).get(name, 0),
            })
        return result

    def route(self, job: Job) -> dict[str, Any]:
        if job.risk not in RISKS:
            raise ValueError(f"risk must be one of {', '.join(RISKS)}")
        if job.deterministic_available:
            return self._decision(job, "deterministic", "LLM unnecessary; deterministic execution is preferred")
        if job.risk == "SENIOR_REVIEW":
            return self._decision(job, "codex", "explicit senior-review class", gated=True)
        if job.risk == "HIGH_RISK":
            return self._decision(job, "codex", "high-risk work requires human/senior gate", gated=True)

        order = self.config["routing"]["tiny" if job.risk == "TINY" else "normal"]
        attempted = []
        for name in order:
            if name == job.exclude_provider:
                attempted.append({"provider": name, "status": "EXCLUDED_FOR_INDEPENDENCE"})
                continue
            provider = self.config["providers"][name]
            status = self.status(name, provider)
            attempted.append({"provider": name, "status": status})
            if status == "READY":
                return self._decision(job, name, "first healthy zero-spend provider", attempted=attempted)
        return {"job_id": job.id, "status": "NO_FREE_PROVIDER_AVAILABLE", "attempted": attempted,
                "retry": False, "max_retries": self.config["policy"]["max_retries"]}

    def _decision(self, job: Job, provider: str, reason: str, gated: bool = False,
                  attempted: list[dict[str, str]] | None = None) -> dict[str, Any]:
        p = self.config["providers"][provider]
        return {"job_id": job.id, "status": "GATED" if gated else "ROUTED", "provider": provider,
                "model": os.environ.get(p.get("model_env", ""), p.get("model")),
                "reason": reason, "human_gate": gated,
                "free_only": p.get("free_only", True), "attempted": attempted or [],
                "max_retries": self.config["policy"]["max_retries"],
                "promotion_requirements": ["deterministic_tests_pass", "base_commit_unchanged"] +
                    (["independent_review"] if job.requires_review and not gated else [])}

    def record(self, provider: str, outcome: str, job_id: str) -> None:
        if provider not in self.config["providers"]:
            raise ValueError("unknown provider")
        health = self.state.setdefault("providers", {}).setdefault(provider, {})
        health["last_outcome"] = outcome
        health["updated_at"] = now()
        if outcome in {"FAILURE", "QUOTA_429"}:
            health["failures"] = health.get("failures", 0) + 1
        elif outcome == "SUCCESS":
            health["failures"] = 0
        if outcome == "QUOTA_429":
            minutes = self.config["policy"]["quota_cooldown_minutes"]
            health["cooldown_until"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).isoformat()
        if outcome != "CREDENTIAL_REQUIRED":
            day = self.state.setdefault("daily_usage", {}).setdefault(dt.date.today().isoformat(), {})
            day[provider] = day.get(provider, 0) + 1
        atomic_json(self.state_path, self.state)
        evidence = {"job_id": job_id, "provider": provider, "outcome": outcome, "recorded_at": now()}
        atomic_json(self.state_dir / "evidence" / f"{job_id}-{int(dt.datetime.now().timestamp())}.json", evidence)


def git_head(repo: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def compact_packet(paths: list[Path], max_bytes: int) -> dict[str, Any]:
    packet: dict[str, Any] = {"created_at": now(), "files": [], "truncated": False}
    used = 0
    forbidden_names = (".env", "auth.json", "id_rsa", "id_ed25519", ".pem", ".key")
    forbidden_parts = (".ssh", ".codex", ".openhands")
    for path in paths:
        parts = path.expanduser().resolve(strict=False).parts
        config_gh = ".config" in parts and "gh" in parts[parts.index(".config") + 1:]
        if (any(token in path.name for token in forbidden_names) or
                any(token in parts for token in forbidden_parts) or config_gh or not path.is_file()):
            continue
        data = path.read_bytes()
        remaining = max_bytes - used
        if remaining <= 0:
            packet["truncated"] = True
            break
        chunk = data[:remaining]
        packet["files"].append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                                "content": chunk.decode("utf-8", errors="replace")})
        used += len(chunk)
        if len(chunk) < len(data):
            packet["truncated"] = True
            break
    packet["bytes"] = used
    return packet


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LifeOS zero-spend AI job governor")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="report provider readiness, cooldowns, failures, and daily usage")
    route = sub.add_parser("route", help="dry-run a routing decision; never invokes a provider")
    route.add_argument("--task", required=True); route.add_argument("--risk", choices=RISKS, default="NORMAL")
    route.add_argument("--deterministic", action="store_true"); route.add_argument("--tiny", action="store_true")
    route.add_argument("--no-review", action="store_true"); route.add_argument("--base-commit")
    route.add_argument("--review-of", choices=("gemini", "groq", "openrouter", "cloudflare"),
                       help="exclude the drafting provider for independent review")
    record = sub.add_parser("record", help="record provider outcome and local evidence")
    record.add_argument("--provider", required=True); record.add_argument("--outcome", required=True,
        choices=("SUCCESS", "FAILURE", "QUOTA_429", "CREDENTIAL_REQUIRED")); record.add_argument("--job-id", required=True)
    context = sub.add_parser("context", help="create a compact, secret-filtered context packet")
    context.add_argument("paths", nargs="+", type=Path); context.add_argument("--max-bytes", type=int, default=32768)
    context.add_argument("--output", type=Path)
    promote = sub.add_parser("check-promotion", help="fail if the repository HEAD changed since job creation")
    promote.add_argument("--repo", type=Path, default=Path.cwd()); promote.add_argument("--base-commit", required=True)
    return p


def main() -> int:
    args = parser().parse_args(); governor = Governor(args.config, args.state_dir)
    if args.command == "health":
        print(json.dumps(governor.health(), indent=2)); return 0
    if args.command == "route":
        job_id = "job-" + hashlib.sha256((args.task + now()).encode()).hexdigest()[:12]
        job = Job(job_id, args.task, "TINY" if args.tiny else args.risk, args.deterministic,
                  not args.tiny, not args.no_review, args.base_commit, args.review_of)
        print(json.dumps(governor.route(job), indent=2)); return 0
    if args.command == "record":
        governor.record(args.provider, args.outcome, args.job_id); return 0
    if args.command == "context":
        packet = compact_packet(args.paths, args.max_bytes)
        if args.output: atomic_json(args.output, packet)
        else: print(json.dumps(packet, indent=2))
        return 0
    if args.command == "check-promotion":
        current = git_head(args.repo)
        print(json.dumps({"base_commit": args.base_commit, "current_commit": current, "unchanged": current == args.base_commit}))
        return 0 if current == args.base_commit else 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
