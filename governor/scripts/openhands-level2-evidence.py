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

SENSITIVE = re.compile(r"(token|secret|password|authorization|cookie|api.?key)", re.I)
PATH_TOKEN = re.compile(r"(?:/projects/[A-Za-z0-9._/-]+|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)")


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


def summarize(root: pathlib.Path) -> dict[str, Any]:
    events = [
        json.loads(path.read_text())
        for path in sorted((root / "events").glob("event-*.json"))
    ]
    base = json.loads((root / "base_state.json").read_text())
    action_kinds: collections.Counter[str] = collections.Counter()
    signatures: list[str] = []
    inspected_paths: set[str] = set()
    issue_935_inspected = False
    empty_agent_messages = 0
    recovery_messages = 0
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    total_tokens: list[int] = []

    for event in events:
        source = event.get("source")
        message = event.get("llm_message") or {}
        content = message.get("content") or []
        if source == "agent" and event.get("kind") == "MessageEvent" and not content:
            empty_agent_messages += 1
        flat = json.dumps(event, sort_keys=True)
        if "Your last response did not include a function call or a message" in flat:
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
                inspected_paths.add(path)
            for candidate in PATH_TOKEN.findall(command):
                if candidate.startswith("/projects/"):
                    inspected_paths.add(candidate)
            lower = (command + " " + path).lower()
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
        "schema_version": 1,
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
        "inspected_paths": sorted(inspected_paths)[:50],
        "usage_samples": {
            "prompt_tokens": prompt_tokens[-20:],
            "completion_tokens": completion_tokens[-20:],
            "total_tokens": total_tokens[-20:],
        },
        "terminal_state": base.get("execution_status"),
        "workspace": base.get("workspace", {}).get("working_dir"),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: openhands-level2-evidence.py CONVERSATION_DIR", file=sys.stderr)
        return 2
    print(json.dumps(summarize(pathlib.Path(sys.argv[1])), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
