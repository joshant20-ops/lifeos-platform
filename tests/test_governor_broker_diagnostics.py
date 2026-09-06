import importlib.util
import pathlib
import sys
import types


# The server loads its runtime core from an installed extensionless path at import
# time, so isolate the pure diagnostic helpers by compiling only their source
# definitions rather than importing the live service entrypoint.
SERVER = pathlib.Path(__file__).resolve().parents[1] / "governor" / "autonomous_agent_server.py"
TEXT = SERVER.read_text()
START = TEXT.index("def _request_shape")
END = TEXT.index("\ndef _broker_chat", START)
NS = {"re": __import__("re")}
exec(TEXT[START:END], NS)
_request_shape = NS["_request_shape"]
_safe_broker_error = NS["_safe_broker_error"]


def test_request_shape_never_contains_message_content():
    body = {
        "messages": [
            {"role": "user", "content": "VERY_PRIVATE_SENTINEL"},
            {"role": "assistant", "content": [{"type": "text", "text": "ANOTHER_SECRET"}], "tool_calls": [{"id": "x"}]},
        ],
        "tools": [{"type": "function", "function": {"name": "shell"}}],
        "tool_choice": "auto",
    }
    got = _request_shape(body)
    assert "VERY_PRIVATE_SENTINEL" not in got
    assert "ANOTHER_SECRET" not in got
    assert "messages=2" in got
    assert "roles=user,assistant" in got
    assert "tools=1" in got
    assert "assistant_tool_calls=1" in got


def test_broker_error_redacts_provider_detail():
    class E(Exception):
        pass
    assert _safe_broker_error(E("provider HTTP 400: secret body")) == "provider_http_400"
    assert _safe_broker_error(E("anything containing SECRET")) == "E"
