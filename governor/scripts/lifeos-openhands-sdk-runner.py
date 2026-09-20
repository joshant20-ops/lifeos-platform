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
    conversation.send_message(prompt)
    conversation.run()
    print("OPENHANDS_SDK_RUNTIME=COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
