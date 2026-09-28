import importlib.util
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
        {"kind": "ActionEvent", "source": "agent", "action": {"kind": "TerminalAction", "command": "gh issue view 935"}},
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
    assert result["schema_version"] == 2
    assert result["activity"] == {
        "tests_executed": True,
        "diff_reviewed": True,
        "commit_attempted": True,
        "push_attempted": True,
        "pr_attempted": True,
        "ci_checked": True,
    }


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
