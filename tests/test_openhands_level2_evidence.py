import importlib.util
import hashlib
import json
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "governor/scripts/openhands-level2-evidence.py"
SPEC = importlib.util.spec_from_file_location("openhands_level2_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_conversation(tmp_path):
    root = tmp_path / "abc"
    events = root / "events"
    events.mkdir(parents=True)
    (root / "base_state.json").write_text(json.dumps({
        "execution_status": "stuck",
        "agent": {"llm": {"model": "openai/gpt-oss:20b", "max_input_tokens": 8192}},
        "workspace": {"working_dir": "/projects/lifeos-platform"},
    }))
    records = [
        {"kind": "MessageEvent", "source": "user", "llm_message": {"content": [{"type": "text", "text": "issue #935"}]}},
        {"kind": "ActionEvent", "source": "agent", "action": {"kind": "TerminalAction", "command": "gh issue view 935 && pytest -q && git diff && git commit -am fix && git push && gh pr create && gh pr checks"}},
        {"kind": "ObservationEvent", "source": "environment", "usage": {"prompt_tokens": 7000, "completion_tokens": 40}},
        {"kind": "ActionEvent", "source": "agent", "action": {"kind": "TerminalAction", "command": "gh issue view 935 && pytest -q && git diff && git commit -am fix && git push && gh pr create && gh pr checks"}},
        {"kind": "MessageEvent", "source": "agent", "llm_message": {"content": []}},
        {"kind": "MessageEvent", "source": "environment", "llm_message": {"content": [{"type": "text", "text": "Your last response did not include a function call or a message. Please use a tool to proceed with the task."}]}},
    ]
    for index, record in enumerate(records):
        (events / f"event-{index:05d}.json").write_text(json.dumps(record))
    return root


def test_summary_is_bounded_and_detects_progress_failure(tmp_path):
    result = MODULE.summarize(write_conversation(tmp_path))
    assert result["effective_model"] == "openai/gpt-oss:20b"
    assert result["configured_context"] == 8192
    assert result["action_count"] == 2
    assert result["action_kinds"] == {"TerminalAction": 2}
    assert result["repeated_action_count"] == 1
    assert result["unique_action_signatures"] == 1
    assert result["issue_935_inspected"] is True
    assert result["empty_agent_messages"] == 1
    assert result["recovery_messages"] == 1
    assert result["usage_samples"]["prompt_tokens"] == [7000]
    assert result["terminal_state"] == "stuck"
    assert result["schema_version"] == 3
    assert result["activity"] == {
        "tests_executed": True,
        "diff_reviewed": True,
        "commit_attempted": True,
        "push_attempted": True,
        "pr_attempted": True,
        "ci_checked": True,
    }


def test_event_trace_records_context_and_order_without_message_payloads(tmp_path):
    root = write_conversation(tmp_path)
    records = [
        {
            "kind": "MessageEvent",
            "source": "user",
            "timestamp": "2026-10-20T00:00:00Z",
            "llm_message": {"role": "user", "content": [{"type": "text", "text": "Issue #935: inspect hardware inventory. PRIVATE BODY"}]},
        },
        {
            "kind": "MessageEvent",
            "source": "agent",
            "timestamp": "2026-10-20T00:00:01Z",
            "llm_message": {"role": "assistant", "content": [{"type": "text", "text": "I will inspect issue #935 and tests."}]},
        },
        {
            "kind": "ActionEvent",
            "source": "agent",
            "timestamp": "2026-10-20T00:00:02Z",
            "tool_call": {"name": "terminal"},
            "action": {"kind": "TerminalAction", "command": "cat /projects/lifeos-platform/tests/test_status.py /home/user/private.txt"},
        },
        {
            "kind": "ObservationEvent",
            "source": "environment",
            "timestamp": "2026-10-20T00:00:03Z",
            "tool_name": "terminal",
            "observation": {"exit_code": 2, "content": [{"text": "PRIVATE ERROR PAYLOAD"}]},
        },
        {
            "kind": "AgentErrorEvent",
            "source": "agent",
            "tool_name": "unsupported-tool",
            "error": "Tool not found; PRIVATE ERROR DETAILS",
        },
        {
            "kind": "MessageEvent",
            "source": "user",
            "llm_message": {"role": "user", "content": [{"type": "text", "text": "Recovery instruction PRIVATE RECOVERY BODY"}]},
        },
    ]
    for index, record in enumerate(records):
        (root / "events" / f"event-{index:05d}.json").write_text(json.dumps(record))

    result = MODULE.summarize(root)
    encoded = json.dumps(result)
    trace = result["event_trace"]

    assert result["initial_context"] == {
        "sha256": hashlib.sha256("Issue #935: inspect hardware inventory. PRIVATE BODY".encode()).hexdigest(),
        "characters": len("Issue #935: inspect hardware inventory. PRIVATE BODY"),
        "issue_references": ["935"],
    }
    assert [entry["kind"] for entry in trace[:6]] == [
        "MessageEvent", "MessageEvent", "ActionEvent", "ObservationEvent",
        "AgentErrorEvent", "MessageEvent",
    ]
    assert trace[0]["message"]["initial_context"] is True
    assert trace[1]["message"]["issue_references"] == ["935"]
    assert trace[2]["action"] == {
        "tool": "terminal",
        "kind": "TerminalAction",
        "repo_paths": ["tests/test_status.py"],
    }
    assert trace[3]["result"] == "error"
    assert trace[3]["exit_code"] == 2
    assert trace[4]["error_class"] == "tool_unavailable"
    assert trace[5]["message"]["recovery_or_followup"] is True
    for private_value in (
        "PRIVATE BODY", "PRIVATE ERROR PAYLOAD", "PRIVATE ERROR DETAILS", "PRIVATE RECOVERY BODY",
        "/home/user/private.txt",
    ):
        assert private_value not in encoded


def test_event_trace_is_capped(tmp_path):
    root = write_conversation(tmp_path)
    events = root / "events"
    for index in range(6, MODULE.MAX_TRACE_EVENTS + 9):
        (events / f"event-{index:05d}.json").write_text(json.dumps({"kind": "OtherEvent", "source": "environment"}))

    result = MODULE.summarize(root)

    assert len(result["event_trace"]) == MODULE.MAX_TRACE_EVENTS
    assert result["event_trace_truncated"] == 9


def test_summary_does_not_emit_secret_values(tmp_path):
    root = write_conversation(tmp_path)
    event = root / "events/event-00006.json"
    event.write_text(json.dumps({
        "kind": "ActionEvent",
        "source": "agent",
        "action": {
            "kind": "TerminalAction",
            "command": "echo safe",
            "GITHUB_TOKEN": "never-print-me",
        },
    }))
    encoded = json.dumps(MODULE.summarize(root))
    assert "never-print-me" not in encoded
    assert "GITHUB_TOKEN" not in encoded
