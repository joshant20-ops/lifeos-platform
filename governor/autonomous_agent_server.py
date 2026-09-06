#!/usr/bin/env python3
"""Single-process LifeOS Governor server with authenticated AI broker endpoint.

This is the service entrypoint.  It reuses the existing autonomous-agent HTTP
handler and adds only the OpenAI-compatible inference surface required by
OpenHands on Engineer. Provider credentials remain on Pi5 inside ai_broker.
"""
from __future__ import annotations

import hmac
import importlib.util
import json
import os
import pathlib
import stat
import time
import urllib.parse
import uuid
from http.server import ThreadingHTTPServer

PLATFORM_REPO = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform")).resolve()
CORE_PATH = pathlib.Path(os.environ.get("LIFEOS_AGENT_CORE", "/usr/local/libexec/lifeos-autonomous-agent-core.py"))
BROKER_PATH = PLATFORM_REPO / "governor" / "ai_broker.py"
BROKER_TOKEN_FILE = pathlib.Path(
    os.environ.get("LIFEOS_AI_BROKER_TOKEN_FILE", pathlib.Path.home() / ".config/lifeos/ai-broker.token")
)


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORE = _load("lifeos_autonomous_agent_core", CORE_PATH)
BROKER = _load("lifeos_ai_broker_runtime", BROKER_PATH)


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
    return bool(
        expected
        and supplied.startswith("Bearer ")
        and hmac.compare_digest(supplied[7:].encode(), expected.encode())
    )


def _broker_chat(body: dict) -> dict:
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages_required")

    lines: list[str] = []
    raw: list[str] = []
    for item in messages[-24:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user"))[:16]
        content = item.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
            )
        content = str(content)[:12000]
        lines.append(f"{role.upper()}: {content}")
        raw.append(content)
    if not lines:
        raise ValueError("messages_required")

    requested_model = str(body.get("model", "lifeos-normal"))
    requested_privacy = "local-only" if "local-only" in requested_model else "normal"
    task_class = "normal"
    for candidate in ("substantial", "review", "normal"):
        if candidate in requested_model:
            task_class = candidate
            break

    detected = CORE.classify_privacy("\n".join(raw))
    privacy = "local-only" if detected == "local-only" else requested_privacy
    routed = BROKER.generate("\n".join(lines), privacy=privacy, task_class=task_class)
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:20],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": routed["model"],
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": routed["text"]},
            "finish_reason": "stop",
        }],
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
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            self.send_json(200, _broker_chat(body))
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except BROKER.BrokerError:
            self.send_json(503, {"error": "inference_unavailable"})
        except Exception as exc:
            self.send_json(502, {"error": "broker_unavailable", "detail": type(exc).__name__})


if __name__ == "__main__":
    print(f"lifeos-autonomous-agent+broker listening on 0.0.0.0:{CORE.PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", CORE.PORT), Handler).serve_forever()
