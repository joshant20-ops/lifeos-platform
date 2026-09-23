#!/usr/bin/env python3
"""Thin LifeOS entrypoint into the OpenHands SDK engineering runtime.

Governor owns policy/routing/power/publication/acceptance. OpenHands owns the
engineering conversation, workspace tools, planning, edits, tests and repair.
This intentionally avoids interpreting OpenHands internal actions in LifeOS.
"""
import os
import re
import sys
from pathlib import Path

from pydantic import SecretStr
from openhands.sdk import LLM, Conversation
from openhands.sdk.event import AgentErrorEvent
from openhands_cli.utils import get_default_cli_agent


def safe_upstream_markers(exception: Exception) -> list[str]:
    """Classify an OpenAI-compatible failure without exposing response content."""
    markers = []
    current = exception
    seen = set()
    combined = []
    while current is not None and id(current) not in seen and len(seen) < 5:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            markers.append(f"OPENHANDS_UPSTREAM_HTTP_STATUS={status}")
        if response is not None:
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", error):
                    markers.append(f"OPENHANDS_UPSTREAM_ERROR_CODE={error}")
                combined.extend(str(payload.get(key) or "") for key in ("detail", "message"))
                if isinstance(error, dict):
                    combined.extend(str(error.get(key) or "") for key in ("detail", "message", "type"))
        current = current.__cause__ or current.__context__
    detail = " ".join(combined).lower()
    provider_statuses = re.findall(r"provider http (\d{3})", detail)
    markers.extend(f"OPENHANDS_PROVIDER_HTTP_STATUS={code}" for code in provider_statuses[:3])
    upstream_classes = sorted(set(re.findall(r"\b([A-Z][A-Za-z]{2,63}Error)\b", " ".join(combined))))
    markers.extend(f"OPENHANDS_UPSTREAM_CLASS={name}" for name in upstream_classes[:5])
    categories = (
        ("memory_capacity", ("system memory", "out of memory", "cuda out of memory")),
        ("context_capacity", ("context length", "context window", "too many tokens")),
        ("ollama_runner_stopped", ("runner has unexpectedly stopped", "model runner", "llama runner")),
        ("local_ai_readiness", ("local ai did not become ready",)),
        ("empty_model_response", ("returned empty", "no tool-aware message")),
        ("provider_http", ("provider http",)),
        ("provider_request", ("provider request failed",)),
        ("provider_exhausted", ("providers exhausted",)),
        ("timeout", ("timed out", "timeout")),
        ("connection", ("connection refused", "connection reset", "network is unreachable")),
    )
    category = next((name for name, terms in categories if any(term in detail for term in terms)), "unclassified")
    markers.append(f"OPENHANDS_UPSTREAM_CATEGORY={category}")
    return list(dict.fromkeys(markers))


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: lifeos-openhands-sdk-runner.py PROMPT_FILE", file=sys.stderr)
        return 2
    prompt = Path(sys.argv[1]).read_text(encoding="utf-8")
    api_key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL")
    base_url = os.environ.get("LLM_BASE_URL")
    if not api_key or not model or not base_url:
        print("OPENHANDS_SDK_ERROR=missing_governor_broker_environment", file=sys.stderr)
        return 20

    llm = LLM(
        usage_id="lifeos-engineer",
        model=model,
        base_url=base_url,
        api_key=SecretStr(api_key),
    )
    # Use OpenHands CLI's own non-interactive agent preset. Besides native
    # engineering tools, this supplies the OTS cli_mode completion discipline
    # and condenser. A plain SDK Agent defaults to conversational behaviour and
    # may legitimately finish after an inspection-only message.
    agent = get_default_cli_agent(llm)
    conversation = Conversation(agent=agent, workspace=os.getcwd())
    print("OPENHANDS_SDK_RUNTIME=START", flush=True)
    engineering_prompt = """You are the repository engineering agent. Work autonomously in the supplied workspace.
Your first action must use the native terminal tool to print the working directory and inspect the repository's real top-level structure. Treat those tool results as the authority for paths: never guess a file or directory, and re-list the relevant parent before creating a new path.
Do not stop at describing, summarising, planning, or proposing commands. Inspect the repository and execute the requested work with native tools.
For audit, verification, cleanup, archive, disposition, or evidence-only tasks, planning to inspect is not progress: actually enumerate and inspect the relevant repository estate in this session. Before finishing, run at least one focused deterministic command whose output directly supports the requested outcome.
If no source change is needed, finish with a concise EVIDENCE section naming the concrete paths/items inspected and the deterministic command/result that proves why no change is needed.
If a prior Governor verifier instruction is present, treat it as mandatory work for this session rather than restating it.
Only finish when the requested task is actually satisfied or a genuine external blocker prevents it.

""" + prompt
    conversation.send_message(engineering_prompt)
    # OpenHands owns the engineering plane. Drive the same persistent conversation
    # until it produces objective completion evidence; Governor remains outside this
    # loop and independently verifies/publishes the resulting handoff.
    try:
        max_turns = int(os.environ.get("LIFEOS_OPENHANDS_MAX_TURNS", "8"))
        for turn in range(1, max_turns + 1):
            conversation.run()
            events_now = list(conversation.state.events)
            errors_now = [event for event in events_now if isinstance(event, AgentErrorEvent)]
            if errors_now:
                break
            engineering_actions = [
                event for event in events_now
                if getattr(event, "action", None) is not None
                and type(getattr(event, "action", None)).__name__.lower() != "finishaction"
            ]
            workspace_dirty = bool(os.popen("git status --porcelain --untracked-files=all").read().strip())
            # A changed workspace is concrete engineering output. For legitimate
            # no-change work, require the agent's own final evidence contract rather
            # than an arbitrary action count.
            messages = [
                str(getattr(event, "message", "") or getattr(event, "content", "") or "")
                for event in events_now
            ]
            evidence_claim = any("EVIDENCE" in message.upper() for message in messages[-8:])
            if workspace_dirty or evidence_claim:
                print(f"OPENHANDS_ENGINEERING_TURNS={turn}", flush=True)
                break
            if turn == max_turns:
                print("OPENHANDS_SDK_ERROR=objective_evidence_not_produced", file=sys.stderr, flush=True)
                return 23
            conversation.send_message(
                "Continue the SAME engineering objective. Do not merely report completion. "
                "Use the repository tools to diagnose, edit and test as needed. Finish only "
                "after the workspace contains the required change, or provide an EVIDENCE "
                "section with concrete deterministic proof that no change is required."
            )
    except Exception as exc:
        # Keep local/private prompts and exception messages out of workflow
        # evidence while preserving categorical SDK boundaries for diagnosis.
        chain = []
        current = exc
        seen = set()
        while current is not None and id(current) not in seen and len(chain) < 5:
            seen.add(id(current))
            chain.append(type(current).__name__)
            current = current.__cause__ or current.__context__
        events = list(conversation.state.events)
        errors = [event for event in events if isinstance(event, AgentErrorEvent)]
        tool_events = [
            event for event in events
            if getattr(event, "action", None) is not None
            and type(getattr(event, "action", None)).__name__.lower().endswith("action")
        ]
        print(
            "OPENHANDS_SDK_ERROR=conversation_exception_chain_" + "__".join(chain),
            file=sys.stderr,
            flush=True,
        )
        print(f"OPENHANDS_SDK_EVENTS_ON_EXCEPTION={len(events)}", file=sys.stderr, flush=True)
        print(f"OPENHANDS_SDK_ERROR_EVENTS_ON_EXCEPTION={len(errors)}", file=sys.stderr, flush=True)
        print(f"OPENHANDS_SDK_TOOL_EVENTS_ON_EXCEPTION={len(tool_events)}", file=sys.stderr, flush=True)
        for marker in safe_upstream_markers(exc):
            print(marker, file=sys.stderr, flush=True)
        return 24
    events = list(conversation.state.events)
    errors = [event for event in events if isinstance(event, AgentErrorEvent)]
    if errors:
        print(f"OPENHANDS_SDK_ERROR=agent_error_event count={len(errors)}", file=sys.stderr, flush=True)
        return 21
    # OpenHands owns engineering completion. LifeOS records native action count only
    # as telemetry; it must never infer task progress or reject completion by count.
    tool_events = [
        event for event in events
        if getattr(event, "action", None) is not None
        and type(getattr(event, "action", None)).__name__.lower().endswith("action")
    ]
    print(f"OPENHANDS_SDK_TOOL_EVENTS={len(tool_events)}", flush=True)
    print("OPENHANDS_SDK_RUNTIME=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
