#!/usr/bin/env python3
"""Bounded, secret-safe evidence summary for a persisted OpenHands conversation."""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib
import re
import sys
from typing import Any

SENSITIVE = re.compile(r"(?:^|[_-])(token|secret|password|authorization|cookie|api.?key|credential)(?:$|[_-])", re.I)
PATH_TOKEN = re.compile(r"/projects/[A-Za-z0-9._/-]+")
ISSUE_REF = re.compile(r"(?<![A-Za-z0-9])#(\d{1,8})\b")
MAX_TRACE_EVENTS = 160
MESSAGE_MARKERS = (
    "issue", "acceptance", "criteria", "task", "defect", "test", "implementation",
    "hardware", "inventory", "status", "candidate", "inspect", "repository", "branch",
    "commit", "push", "pull request", "ci", "error", "blocked", "clarify", "question",
)


def walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            if SENSITIVE.search(str(key)):
                continue
            yield from walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")
    else:
        yield path, value


def action_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    action = event.get("action")
    if isinstance(action, dict):
        return action
    if event.get("kind") == "ActionEvent":
        return {
            key: value
            for key, value in event.items()
            if key not in {"id", "timestamp", "source", "kind"}
        }
    return None


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content") or []
    return "\n".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )


def context_identity(text: str) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "characters": len(text),
        "issue_references": sorted(set(ISSUE_REF.findall(text)))[:30],
    }


def _safe_repo_path(value: str, workspace: str) -> str | None:
    candidate = pathlib.PurePosixPath(value.strip().strip("'\"`;,()"))
    root = pathlib.PurePosixPath(workspace)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return None
    else:
        relative = candidate
    if not relative.parts or any(part in {"..", "."} for part in relative.parts):
        return "." if str(relative) == "." else None
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in relative.parts):
        return None
    return relative.as_posix()


def _tool_error_class(value: Any) -> str:
    text = str(value or "").lower()
    if "not found" in text or "available:" in text:
        return "tool_unavailable"
    if "validat" in text or "missing required" in text or "extra inputs" in text:
        return "argument_schema"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "other"


def event_trace(events: list[dict[str, Any]], workspace: str) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    first_user_message_seen = False
    for index, event in enumerate(events[:MAX_TRACE_EVENTS]):
        kind = str(event.get("kind") or "unknown")[:48]
        source = str(event.get("source") or "unknown")[:24]
        item: dict[str, Any] = {"index": index, "kind": kind, "source": source}
        timestamp = event.get("timestamp")
        if isinstance(timestamp, str):
            item["timestamp"] = timestamp[:40]

        if kind == "MessageEvent":
            message = event.get("llm_message") or {}
            text = message_text(message)
            role = str(message.get("role") or source)[:24]
            is_first_user = role == "user" and not first_user_message_seen
            if role == "user":
                first_user_message_seen = True
            item["message"] = {
                "role": role,
                "characters": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "issue_references": sorted(set(ISSUE_REF.findall(text)))[:30],
                "markers": [marker for marker in MESSAGE_MARKERS if marker in text.lower()][:20],
                "initial_context": is_first_user,
                "recovery_or_followup": role == "user" and not is_first_user,
            }
            tool_calls = message.get("tool_calls") or []
            if isinstance(tool_calls, list) and tool_calls:
                item["message"]["tool_names"] = [
                    str(call.get("function", {}).get("name") or call.get("name") or "unknown")[:64]
                    for call in tool_calls[:8]
                    if isinstance(call, dict)
                ]
        elif kind == "ActionEvent":
            action = action_payload(event) or {}
            call = event.get("tool_call") or {}
            tool = call.get("name") or event.get("tool_name") or action.get("tool_name")
            item["action"] = {
                "tool": str(tool or "unknown")[:64],
                "kind": str(action.get("kind") or action.get("type") or "unknown")[:64],
            }
            paths: set[str] = set()
            path = action.get("path")
            if isinstance(path, str):
                safe = _safe_repo_path(path, workspace)
                if safe:
                    paths.add(safe)
            command = action.get("command")
            if isinstance(command, str):
                for candidate in PATH_TOKEN.findall(command):
                    safe = _safe_repo_path(candidate, workspace)
                    if safe:
                        paths.add(safe)
            if paths:
                item["action"]["repo_paths"] = sorted(paths)[:8]
        elif kind == "ObservationEvent":
            observation = event.get("observation") or {}
            error = observation.get("is_error") is True
            exit_code = observation.get("exit_code")
            if isinstance(exit_code, int) and exit_code != 0:
                error = True
            item["result"] = "error" if error else "success"
            if isinstance(exit_code, int):
                item["exit_code"] = exit_code
            tool = event.get("tool_name")
            if isinstance(tool, str):
                item["tool"] = tool[:64]
        elif kind == "AgentErrorEvent":
            item["tool"] = str(event.get("tool_name") or "unknown")[:64]
            item["error_class"] = _tool_error_class(event.get("error"))
        trace.append(item)
    return trace


def summarize(root: pathlib.Path) -> dict[str, Any]:
    events = [
        json.loads(path.read_text())
        for path in sorted((root / "events").glob("event-*.json"))
    ]
    base = json.loads((root / "base_state.json").read_text())
    workspace = str(base.get("workspace", {}).get("working_dir") or "")
    action_kinds: collections.Counter[str] = collections.Counter()
    signatures: list[str] = []
    inspected_paths: set[str] = set()
    issue_935_inspected = False
    empty_agent_messages = 0
    recovery_messages = 0
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    total_tokens: list[int] = []
    activity = {
        "tests_executed": False,
        "diff_reviewed": False,
        "commit_attempted": False,
        "push_attempted": False,
        "pr_attempted": False,
        "ci_checked": False,
    }
    initial_context: dict[str, Any] | None = None

    for event in events:
        source = event.get("source")
        message = event.get("llm_message") or {}
        content = message.get("content") or []
        text = message_text(message)
        role = message.get("role") or source
        if role == "user" and initial_context is None:
            initial_context = context_identity(text)
        if source == "agent" and event.get("kind") == "MessageEvent" and not content:
            empty_agent_messages += 1
        if "Your last response did not include a function call or a message" in text:
            recovery_messages += 1

        action = action_payload(event)
        if action:
            kind = str(action.get("kind") or action.get("type") or "unknown")
            action_kinds[kind] += 1
            stable = {
                key: value
                for key, value in action.items()
                if key not in {"id", "timestamp", "thought", "reasoning"}
                and not SENSITIVE.search(str(key))
            }
            signature = hashlib.sha256(
                json.dumps(stable, sort_keys=True, default=str).encode()
            ).hexdigest()[:12]
            signatures.append(signature)
            command = str(action.get("command") or "")
            path = str(action.get("path") or "")
            if path:
                safe = _safe_repo_path(path, workspace)
                if safe:
                    inspected_paths.add(safe)
            for candidate in PATH_TOKEN.findall(command):
                safe = _safe_repo_path(candidate, workspace)
                if safe:
                    inspected_paths.add(safe)
            lower = (command + " " + path).lower()
            activity["tests_executed"] |= bool(re.search(
                r"(^|[;&| ]|python -m )(pytest|unittest|npm test|npm run test|go test|cargo test|make test)([ ;&|]|$)",
                command,
                re.I,
            ))
            activity["diff_reviewed"] |= "git diff" in lower
            activity["commit_attempted"] |= "git commit" in lower
            activity["push_attempted"] |= "git push" in lower
            activity["pr_attempted"] |= bool(re.search(r"\bgh\s+pr\s+create\b", command))
            activity["ci_checked"] |= bool(re.search(
                r"\bgh\s+(pr\s+checks|run\s+(watch|view|list))\b", command
            ))
            if (
                ("issue" in lower and "935" in lower)
                or "/issues/935" in lower
                or "issues/935" in lower
            ):
                issue_935_inspected = True

        for path, value in walk(event):
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            leaf = path.rsplit(".", 1)[-1].lower()
            if leaf in {"prompt_tokens", "input_tokens", "prompt_eval_count"}:
                prompt_tokens.append(value)
            elif leaf in {"completion_tokens", "output_tokens", "eval_count"}:
                completion_tokens.append(value)
            elif leaf == "total_tokens":
                total_tokens.append(value)

    repeated = sum(count - 1 for count in collections.Counter(signatures).values() if count > 1)
    llm = base.get("agent", {}).get("llm", {})
    configured_context = next(
        (
            llm.get(key)
            for key in (
                "max_input_tokens",
                "context_window",
                "num_ctx",
                "max_context_tokens",
            )
            if isinstance(llm.get(key), int)
        ),
        None,
    )
    return {
        "schema_version": 3,
        "conversation_id": root.name,
        "effective_model": llm.get("model"),
        "configured_context": configured_context,
        "events": len(events),
        "action_count": sum(action_kinds.values()),
        "action_kinds": dict(sorted(action_kinds.items())),
        "repeated_action_count": repeated,
        "unique_action_signatures": len(set(signatures)),
        "empty_agent_messages": empty_agent_messages,
        "recovery_messages": recovery_messages,
        "issue_935_inspected": issue_935_inspected,
        "activity": activity,
        "inspected_paths": sorted(inspected_paths)[:50],
        "initial_context": initial_context,
        "event_trace": event_trace(events, workspace),
        "event_trace_truncated": max(0, len(events) - MAX_TRACE_EVENTS),
        "usage_samples": {
            "prompt_tokens": prompt_tokens[-20:],
            "completion_tokens": completion_tokens[-20:],
            "total_tokens": total_tokens[-20:],
        },
        "terminal_state": base.get("execution_status"),
        "workspace": workspace,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: openhands-level2-evidence.py CONVERSATION_DIR", file=sys.stderr)
        return 2
    print(json.dumps(summarize(pathlib.Path(sys.argv[1])), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
