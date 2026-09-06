#!/usr/bin/env python3
"""Compatibility helpers for OpenAI-shaped agent requests.

Gemini function declarations accept a constrained JSON-schema/OpenAPI subset.
Agent frameworks commonly emit richer JSON Schema. Strip unsupported metadata
and conservatively collapse unions so tool-calling requests remain portable.
"""
from __future__ import annotations

_ALLOWED = {
    "type", "description", "properties", "required", "items", "enum",
    "minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength",
    "nullable",
}


def _merge_union(branches: list[dict]) -> dict:
    """Choose the most informative compatible branch from a JSON-schema union."""
    usable = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
    if not usable:
        return {"type": "string", "nullable": True}
    chosen = max(usable, key=lambda b: len(b.get("properties", {})) if isinstance(b.get("properties"), dict) else len(b))
    out = dict(chosen)
    if len(usable) != len(branches):
        out["nullable"] = True
    return out


def sanitize_schema(schema) -> dict:
    """Return a Gemini-safe schema without mutating the caller's value."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    source = dict(schema)
    for key in ("anyOf", "oneOf"):
        branches = source.get(key)
        if isinstance(branches, list) and branches:
            merged = _merge_union(branches)
            # Preserve a useful outer description when the union branch lacks it.
            if source.get("description") and not merged.get("description"):
                merged["description"] = source["description"]
            source = merged
            break

    if isinstance(source.get("allOf"), list) and source["allOf"]:
        source = _merge_union(source["allOf"])

    out: dict = {}
    for key, value in source.items():
        if key not in _ALLOWED:
            continue
        if key == "properties":
            if isinstance(value, dict):
                out[key] = {str(name): sanitize_schema(child) for name, child in value.items()}
            continue
        if key == "items":
            out[key] = sanitize_schema(value)
            continue
        if key == "required":
            if isinstance(value, list):
                out[key] = [str(item) for item in value]
            continue
        if key == "enum":
            if isinstance(value, list):
                out[key] = value
            continue
        out[key] = value

    typ = out.get("type")
    if isinstance(typ, list):
        non_null = [str(t) for t in typ if t != "null"]
        out["type"] = non_null[0] if non_null else "string"
        if len(non_null) != len(typ):
            out["nullable"] = True
    if not isinstance(out.get("type"), str):
        out["type"] = "object" if "properties" in out else "string"
    if out["type"] == "object":
        out.setdefault("properties", {})
    return out


def sanitize_tools(tools) -> list[dict]:
    result: list[dict] = []
    if not isinstance(tools, list):
        return result
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = tool.get("function")
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        result.append({
            "type": "function",
            "function": {
                "name": str(fn["name"]),
                "description": str(fn.get("description") or "")[:4000],
                "parameters": sanitize_schema(fn.get("parameters") or {"type": "object", "properties": {}}),
            },
        })
    return result
