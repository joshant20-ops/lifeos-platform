from governor.openai_compat import sanitize_schema, sanitize_tools


def test_sanitize_schema_strips_unsupported_keywords_and_preserves_shape():
    schema = {
        "type": "object",
        "title": "Ignored",
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "format": "path", "pattern": "^/"},
            "mode": {"anyOf": [{"type": "string", "enum": ["read", "write"]}, {"type": "null"}]},
            "opts": {
                "type": "object",
                "properties": {"force": {"type": "boolean", "default": False}},
                "required": ["force"],
            },
        },
        "required": ["path"],
    }
    got = sanitize_schema(schema)
    assert got == {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "mode": {"type": "string", "enum": ["read", "write"], "nullable": True},
            "opts": {
                "type": "object",
                "properties": {"force": {"type": "boolean"}},
                "required": ["force"],
            },
        },
        "required": ["path"],
    }


def test_sanitize_tools_keeps_only_function_tools():
    tools = [
        {"type": "function", "function": {"name": "shell", "description": "run", "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "$comment": "x"}}}}},
        {"type": "web_search"},
    ]
    got = sanitize_tools(tools)
    assert len(got) == 1
    assert got[0]["function"]["name"] == "shell"
    assert got[0]["function"]["parameters"]["properties"]["cmd"] == {"type": "string"}
