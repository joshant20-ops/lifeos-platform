#!/usr/bin/env python3
"""Single-process LifeOS Governor server with authenticated AI broker endpoint."""
from __future__ import annotations

import hmac
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import stat
import time
import urllib.parse
import uuid
from http.server import ThreadingHTTPServer

PLATFORM_REPO = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform")).resolve()
CORE_PATH = pathlib.Path(os.environ.get("LIFEOS_AGENT_CORE", "/usr/local/libexec/lifeos-autonomous-agent-core"))
BROKER_PATH = PLATFORM_REPO / "governor" / "ai_broker.py"
COMPAT_PATH = PLATFORM_REPO / "governor" / "openai_compat.py"
BROKER_TOKEN_FILE = pathlib.Path(
    os.environ.get("LIFEOS_AI_BROKER_TOKEN_FILE", pathlib.Path.home() / ".config/lifeos/ai-broker.token")
)


def _load(name: str, path: pathlib.Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise RuntimeError(f"unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


CORE = _load("lifeos_autonomous_agent_core", CORE_PATH)
BROKER = _load("lifeos_ai_broker_runtime", BROKER_PATH)
COMPAT = _load("lifeos_openai_compat_runtime", COMPAT_PATH)


def _token() -> str:
    try:
        if not BROKER_TOKEN_FILE.is_file() or BROKER_TOKEN_FILE.is_symlink():
            return ""
        if stat.S_IMODE(BROKER_TOKEN_FILE.stat().st_mode) != 0o600:
            return ""
        return BROKER_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _authorized(headers) -> bool:
    expected = _token()
    supplied = str(headers.get("Authorization", ""))
    return bool(expected and supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:].encode(), expected.encode()))


def _privacy_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for item in messages[-32:]:
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").lower() == "system":
            continue
        content = item.get("content")
        if isinstance(content, list):
            content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        if content:
            parts.append(str(content)[:12000])
    return "\n".join(parts)


def _request_shape(body: dict) -> str:
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    roles = []
    content_kinds = []
    tool_calls = 0
    for item in messages[-64:]:
        if not isinstance(item, dict):
            continue
        roles.append(str(item.get("role") or "unknown")[:16])
        content = item.get("content")
        content_kinds.append("list" if isinstance(content, list) else type(content).__name__[:12])
        calls = item.get("tool_calls")
        if isinstance(calls, list):
            tool_calls += len(calls)
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    choice = body.get("tool_choice")
    choice_kind = type(choice).__name__
    choice_value = str(choice)[:32] if isinstance(choice, str) else choice_kind
    return (
        f"messages={len(messages)} roles={','.join(roles[-16:]) or 'none'} "
        f"content_kinds={','.join(content_kinds[-16:]) or 'none'} tools={len(tools)} "
        f"assistant_tool_calls={tool_calls} tool_choice={choice_value}"
    )


def _safe_broker_error(exc: Exception) -> str:
    text = str(exc)
    if text.startswith("tool-capable providers exhausted:"):
        return re.sub(r"[^A-Za-z0-9:_,-]+", "_", text)[:240]
    if text.startswith("eligible providers exhausted:"):
        return re.sub(r"[^A-Za-z0-9:_,-]+", "_", text)[:240]
    if text.startswith("provider HTTP "):
        match = re.match(r"provider HTTP (\d+)", text)
        return f"provider_http_{match.group(1)}" if match else "provider_http_error"
    known = {
        "no eligible tool-capable cloud provider": "no_tool_provider",
        "tool-enabled private inference is not permitted": "private_tool_blocked",
        "gemini returned no candidate": "gemini_no_candidate",
        "gemini returned empty tool-aware response": "gemini_empty_tool_response",
        "provider returned no tool-aware choice": "openai_no_tool_choice",
        "provider returned no tool-aware message": "openai_no_tool_message",
        "provider returned empty tool-aware response": "openai_empty_tool_response",
    }
    return known.get(text, type(exc).__name__)


def _broker_chat(body: dict) -> dict:
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages_required")

    requested_model = str(body.get("model", "lifeos-normal"))
    requested_privacy = "local-only" if "local-only" in requested_model else "normal"
    trusted_engineering = requested_model.startswith("openai/lifeos-engineering-") or requested_model.startswith("lifeos-engineering-")
    task_class = "normal"
    for candidate in ("substantial", "review", "normal"):
        if candidate in requested_model:
            task_class = candidate
            break

    raw = _privacy_text(messages)
    detected = CORE.classify_privacy(raw)
    if trusted_engineering and requested_privacy == "normal":
        privacy = "normal"
    else:
        privacy = "local-only" if detected == "local-only" else requested_privacy
    tools = body.get("tools") or []

    if tools:
        if not isinstance(tools, list):
            raise ValueError("tools_must_be_list")
        tools = COMPAT.sanitize_tools(tools)
        if not tools:
            raise ValueError("function_tools_required")
        routed = BROKER.chat(
            messages,
            tools=tools,
            tool_choice=body.get("tool_choice"),
            privacy=privacy,
            task_class=task_class,
        )
        message = routed["message"]
        finish_reason = routed["finish_reason"]
    else:
        lines: list[str] = []
        for item in messages[-24:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "user"))[:16]
            content = item.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            lines.append(f"{role.upper()}: {str(content)[:12000]}")
        routed = BROKER.generate("\n".join(lines), privacy=privacy, task_class=task_class)
        message = {"role": "assistant", "content": routed["text"]}
        finish_reason = "stop"

    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:20],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": routed["model"],
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "lifeos_provider": routed["provider"],
        "lifeos_privacy": privacy,
        "lifeos_task_class": task_class,
    }


class Handler(CORE.Handler):
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/v1/chat/completions":
            return super().do_POST()
        if not _authorized(self.headers):
            self.send_json(401, {"error": "broker_capability_required"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = {}
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            self.send_json(200, _broker_chat(body))
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except BROKER.BrokerError as exc:
            print(f"BROKER_FAILURE={_safe_broker_error(exc)} {_request_shape(body)}", flush=True)
            self.send_json(503, {"error": "inference_unavailable"})
        except Exception as exc:
            print(f"BROKER_RUNTIME_FAILURE={type(exc).__name__} {_request_shape(body)}", flush=True)
            self.send_json(502, {"error": "broker_unavailable", "detail": type(exc).__name__})


if __name__ == "__main__":
    print(f"lifeos-autonomous-agent+broker listening on 0.0.0.0:{CORE.PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", CORE.PORT), Handler).serve_forever()
