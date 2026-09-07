import ast
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "governor" / "autonomous_agent_server.py"


def _privacy_text_function():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "_privacy_text"
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["_privacy_text"]


def test_system_policy_vocabulary_does_not_force_privacy_classification_input():
    privacy_text = _privacy_text_function()
    messages = [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": "private documents paperless bank statements"}
            ],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "implement sanitized repository integration"}],
        },
    ]
    text = privacy_text(messages)
    assert text == "implement sanitized repository integration"
    assert "paperless" not in text
    assert "bank statements" not in text


def test_user_and_tool_payloads_remain_in_privacy_classification_input():
    privacy_text = _privacy_text_function()
    messages = [
        {"role": "user", "content": "my bank statements"},
        {"role": "assistant", "content": "checking"},
        {"role": "tool", "content": "private documents"},
    ]
    text = privacy_text(messages)
    assert "my bank statements" in text
    assert "checking" in text
    assert "private documents" in text
