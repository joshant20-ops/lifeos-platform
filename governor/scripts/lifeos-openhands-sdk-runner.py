#!/usr/bin/env python3
"""Thin LifeOS entrypoint into the OpenHands SDK engineering runtime.

Governor owns policy/routing/power/publication/acceptance. OpenHands owns the
engineering conversation, workspace tools, planning, edits, tests and repair.
This intentionally avoids interpreting OpenHands internal actions in LifeOS.
"""
import os
import sys
from pathlib import Path

from pydantic import SecretStr
from openhands.sdk import LLM, Agent, Conversation
from openhands.sdk.event import AgentErrorEvent
from openhands.sdk.tool import Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.terminal import TerminalTool


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
    # Give the OTS agent its native engineering tools directly. Do not make
    # LifeOS execute/interpret invoke_skill or terminal actions on its behalf.
    agent = Agent(
        llm=llm,
        tools=[Tool(name=TerminalTool.name), Tool(name=FileEditorTool.name)],
    )
    conversation = Conversation(agent=agent, workspace=os.getcwd())
    print("OPENHANDS_SDK_RUNTIME=START", flush=True)
    engineering_prompt = """You are the repository engineering agent. Work autonomously in the supplied workspace.\nDo not stop at describing, summarising, or proposing commands. Inspect the repository, make the requested repository changes with your native tools, run focused deterministic verification, and only finish when the requested task is actually satisfied or a genuine external blocker prevents it.\n\n""" + prompt
    conversation.send_message(engineering_prompt)
    # Conversation.run() drives the session to completion but the installed SDK
    # returns None. Read the persisted conversation event log afterwards instead
    # of treating run()'s transport return value as an event collection.
    conversation.run()
    events = list(conversation.state.events)
    errors = [event for event in events if isinstance(event, AgentErrorEvent)]
    if errors:
        print(f"OPENHANDS_SDK_ERROR=agent_error_event count={len(errors)}", file=sys.stderr, flush=True)
        return 21
    # A normal SDK return is transport completion only. Require the OTS session to
    # have actually exercised an engineering tool before reporting success; otherwise
    # a model that merely explains the requested edit is indistinguishable from work.
    # OpenHands records native tool use as AgentAction events (for example
    # FileEditorAction/TerminalAction), not as event classes containing "tool".
    # Detect the SDK's action payload generically rather than interpreting or
    # executing individual actions in LifeOS.
    tool_events = [
        event for event in events
        if getattr(event, "action", None) is not None
        and type(getattr(event, "action", None)).__name__.lower().endswith("action")
    ]
    if not tool_events:
        print("OPENHANDS_SDK_ERROR=no_engineering_tool_activity", file=sys.stderr, flush=True)
        return 22
    print(f"OPENHANDS_SDK_TOOL_EVENTS={len(tool_events)}", flush=True)
    print("OPENHANDS_SDK_RUNTIME=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
