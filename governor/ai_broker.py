#!/usr/bin/env python3
"""Deterministic LifeOS AI broker.

The broker owns provider policy and secrets on Pi5. It sends local-only work only
to Ollama and sends cloud-safe work directly to approved cloud APIs without
requiring OpenHands or Engineer to be online.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = pathlib.Path(os.environ.get("LIFEOS_AI_POLICY", ROOT / "governor" / "policy.json"))
SECRETS_PATH = pathlib.Path(
    os.environ.get("LIFEOS_PROVIDER_SECRETS", pathlib.Path.home() / ".config/lifeos/provider-secrets.env")
)
CONFIG_PATH = pathlib.Path(
    os.environ.get("LIFEOS_AI_BROKER_CONFIG", pathlib.Path.home() / ".config/lifeos/ai-broker.env")
)
OLLAMA_URL = os.environ.get("LIFEOS_LOCAL_AI_URL", "http://192.168.0.201:11434/api/generate")
OLLAMA_MODEL = os.environ.get("LIFEOS_LOCAL_AI_MODEL", "qwen2.5-coder:7b-instruct")
HTTP_TIMEOUT = int(os.environ.get("LIFEOS_AI_HTTP_TIMEOUT", "120"))
WAKE_TIMEOUT = int(os.environ.get("LIFEOS_LOCAL_AI_WAKE_TIMEOUT", "90"))
LEASE_TTL = int(os.environ.get("LIFEOS_LOCAL_AI_LEASE_TTL", "1200"))
MQTT_HOST = os.environ.get("LIFEOS_MQTT_HOST", "127.0.0.1")


class BrokerError(RuntimeError):
    pass


def _lease_topic() -> str:
    return f"lifeos/tower/lease/{os.getpid()}"


def _publish_lease(state: str, *, required: bool = True) -> None:
    payload = json.dumps({
        "owner": f"ai-broker:{os.getpid()}",
        "state": state,
        "expires_at": int(time.time()) + (LEASE_TTL if state == "active" else 0),
    }, separators=(",", ":"))
    try:
        subprocess.run(
            ["mosquitto_pub", "-h", MQTT_HOST, "-t", _lease_topic(), "-m", payload, "-r"],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        if required:
            raise BrokerError(f"Tower compute lease unavailable: {type(exc).__name__}") from exc


def _router_module():
    path = ROOT / "engineer" / "provider_router.py"
    spec = importlib.util.spec_from_file_location("lifeos_provider_router", path)
    if spec is None or spec.loader is None:
        raise BrokerError("provider router unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROUTER = _router_module()


def _strict_env(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        return {}
    ROUTER.load_secret_names(path)
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        if sep and value:
            values[name] = value
    return values


def _broker_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for raw in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and name and value:
            values[name] = value
    return values


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: int = HTTP_TIMEOUT) -> dict:
    data = json.dumps(payload, separators=(",", ":")).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise BrokerError(f"provider HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise BrokerError(f"provider request failed: {type(exc).__name__}") from exc


def _provider_model(provider: dict) -> str:
    model = str(provider.get("api_model") or "")
    if not model:
        raise BrokerError(f"provider {provider.get('id')} has no api_model")
    return model


def _wake_local_ai() -> bool:
    cfg = _broker_config()
    mac = os.environ.get("LIFEOS_LOCAL_AI_MAC") or cfg.get("LIFEOS_LOCAL_AI_MAC")
    if not mac:
        raise BrokerError(
            "TOWER_WAKE_CONFIGURATION_ERROR: "
            "LIFEOS_LOCAL_AI_MAC is not configured"
        )
    compact = mac.replace(":", "").replace("-", "")
    if len(compact) != 12:
        raise BrokerError("invalid local AI MAC")
    try:
        mac_bytes = bytes.fromhex(compact)
    except ValueError as exc:
        raise BrokerError("invalid local AI MAC") from exc
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ("255.255.255.255", 9))
    return True


def _ollama_once(prompt: str, model: str) -> str:
    result = _post_json(OLLAMA_URL, {"model": model, "prompt": prompt, "stream": False, "keep_alive": "30m"}, timeout=HTTP_TIMEOUT)
    text = str(result.get("response", "")).strip()
    if not text:
        raise BrokerError("ollama returned empty response")
    return text


def _ollama(prompt: str, model: str) -> str:
    _publish_lease("active")
    try:
        try:
            return _ollama_once(prompt, model)
        except BrokerError as first:
            # The Tower controller consumes the active lease and owns WoL. Keep
            # the direct packet as a compatibility fallback during deployment.
            _wake_local_ai()
            deadline = time.monotonic() + WAKE_TIMEOUT
            last: Exception = first
            while time.monotonic() < deadline:
                time.sleep(3)
                _publish_lease("active")
                try:
                    return _ollama_once(prompt, model)
                except BrokerError as exc:
                    last = exc
            raise BrokerError("local AI did not become ready after Wake-on-LAN") from last
    finally:
        # A retained TTL still releases the lease if MQTT disappears after the
        # request; never replace a useful model result with a cleanup error.
        _publish_lease("released", required=False)


def _ollama_tool_call_from_content(content, tools: list[dict]) -> dict | None:
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        value = json.loads(content)
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    arguments = value.get("arguments")
    if not isinstance(name, str) or not name or not isinstance(arguments, dict):
        return None
    allowed = {
        str((tool.get("function") or {}).get("name") or "")
        for tool in tools
        if isinstance(tool, dict) and tool.get("type") == "function"
    }
    if name not in allowed:
        return None
    return {
        "id": f"call_ollama_{os.urandom(6).hex()}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, separators=(",", ":")),
        },
    }


def _ollama_chat_once(messages: list[dict], tools: list[dict], model: str) -> dict:
    ollama_messages: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "assistant":
            item: dict = {"role": "assistant", "content": str(message.get("content") or "")}
            calls = []
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                if not name:
                    continue
                raw = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    args = {}
                calls.append({"function": {"name": name, "arguments": args if isinstance(args, dict) else {}}})
            if calls:
                item["tool_calls"] = calls
            ollama_messages.append(item)
            continue
        if role == "tool":
            ollama_messages.append({"role": "tool", "content": str(message.get("content") or "")})
            continue
        ollama_messages.append({"role": role, "content": str(message.get("content") or "")})

    if not tools:
        raise BrokerError("tool-aware chat requires function declarations")
    url = OLLAMA_URL.rsplit("/api/", 1)[0] + "/api/chat"
    result = _post_json(url, {
        "model": model,
        "messages": ollama_messages,
        "tools": tools,
        "stream": False,
        "keep_alive": "30m",
    }, timeout=HTTP_TIMEOUT)
    raw_message = result.get("message")
    if not isinstance(raw_message, dict):
        raise BrokerError("ollama returned no tool-aware message")

    content = raw_message.get("content")
    normalized_calls: list[dict] = []
    for index, call in enumerate(raw_message.get("tool_calls") or []):
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        if not name:
            continue
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if not isinstance(args, dict):
            args = {}
        normalized_calls.append({
            "id": str(call.get("id") or f"call_ollama_{index}_{os.urandom(4).hex()}"),
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args, separators=(",", ":")),
            },
        })

    if not normalized_calls:
        fallback = _ollama_tool_call_from_content(content, tools)
        if fallback:
            normalized_calls.append(fallback)
            content = None

    message: dict = {"role": "assistant", "content": content or None}
    if normalized_calls:
        message["tool_calls"] = normalized_calls
    if not normalized_calls and not message["content"]:
        raise BrokerError("ollama returned empty tool-aware response")
    return {
        "message": message,
        "finish_reason": "tool_calls" if normalized_calls else "stop",
    }


def _ollama_chat(messages: list[dict], tools: list[dict], provider: dict, tool_choice=None) -> dict:
    del tool_choice  # Ollama receives the declared tools; model decides the call.
    model = _provider_model(provider)
    _publish_lease("active")
    try:
        try:
            return _ollama_chat_once(messages, tools, model)
        except BrokerError as first:
            _wake_local_ai()
            deadline = time.monotonic() + WAKE_TIMEOUT
            last: Exception = first
            while time.monotonic() < deadline:
                time.sleep(3)
                _publish_lease("active")
                try:
                    return _ollama_chat_once(messages, tools, model)
                except BrokerError as exc:
                    last = exc
            raise BrokerError("local AI did not become ready after Wake-on-LAN") from last
    finally:
        _publish_lease("released", required=False)


def _gemini_url(provider: dict, secrets: dict[str, str]) -> str:
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(_provider_model(provider), safe="-._")
        + ":generateContent?key="
        + urllib.parse.quote(secrets["GEMINI_API_KEY"], safe="")
    )


def _gemini(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    result = _post_json(_gemini_url(provider, secrets), {"contents": [{"parts": [{"text": prompt}]}]})
    candidates = result.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise BrokerError("gemini returned empty response")
    return text


def _jsonish_tool_response(value):
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return {"result": value}
    text = str(value)
    try:
        return {"result": json.loads(text)}
    except Exception:
        return {"result": text}


def _gemini_chat(messages: list[dict], tools: list[dict], provider: dict, secrets: dict[str, str], tool_choice=None) -> dict:
    system_parts: list[str] = []
    contents: list[dict] = []
    call_names: dict[str, str] = {}

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "system":
            content = message.get("content")
            if content:
                system_parts.append(str(content))
            continue
        if role == "assistant":
            parts: list[dict] = []
            content = message.get("content")
            if content:
                parts.append({"text": str(content)})
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                if not name:
                    continue
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    args = {}
                call_id = str(call.get("id") or "")
                if call_id:
                    call_names[call_id] = name
                part = {"functionCall": {"name": name, "args": args if isinstance(args, dict) else {}}}
                if call_id:
                    part["functionCall"]["id"] = call_id
                parts.append(part)
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            name = call_names.get(call_id) or str(message.get("name") or "tool")
            response = {"name": name, "response": _jsonish_tool_response(message.get("content"))}
            if call_id:
                response["id"] = call_id
            contents.append({"role": "user", "parts": [{"functionResponse": response}]})
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        contents.append({"role": "user", "parts": [{"text": str(content or "")}]})

    declarations = []
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = tool.get("function") or {}
        name = str(fn.get("name") or "")
        if not name:
            continue
        declarations.append({
            "name": name,
            "description": str(fn.get("description") or "")[:4000],
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    if not declarations:
        raise BrokerError("tool-aware chat requires function declarations")

    payload: dict = {"contents": contents, "tools": [{"functionDeclarations": declarations}]}
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
    if tool_choice == "required":
        payload["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}

    result = _post_json(_gemini_url(provider, secrets), payload)
    candidates = result.get("candidates") or []
    if not candidates:
        raise BrokerError("gemini returned no candidate")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    texts: list[str] = []
    tool_calls: list[dict] = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        if part.get("text"):
            texts.append(str(part["text"]))
        call = part.get("functionCall")
        if isinstance(call, dict) and call.get("name"):
            call_id = str(call.get("id") or f"call_gemini_{index}")
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": str(call["name"]),
                    "arguments": json.dumps(call.get("args") or {}, separators=(",", ":")),
                },
            })
    message: dict = {"role": "assistant", "content": "\n".join(texts).strip() or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if not tool_calls and not message["content"]:
        raise BrokerError("gemini returned empty tool-aware response")
    return {"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}


def _openai_compatible(url: str, prompt: str, model: str, token: str) -> str:
    result = _post_json(url, {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}, headers={"Authorization": f"Bearer {token}"})
    choices = result.get("choices") or []
    text = str(((choices[0].get("message") or {}).get("content") or "") if choices else "").strip()
    if not text:
        raise BrokerError("provider returned empty response")
    return text


def _openai_chat(url: str, messages: list[dict], tools: list[dict], model: str, token: str, tool_choice=None) -> dict:
    payload: dict = {"model": model, "messages": messages, "tools": tools, "temperature": 0}
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    result = _post_json(url, payload, headers={"Authorization": f"Bearer {token}"})
    choices = result.get("choices") or []
    if not choices:
        raise BrokerError("provider returned no tool-aware choice")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else None
    if not message:
        raise BrokerError("provider returned no tool-aware message")
    content = message.get("content")
    tool_calls = message.get("tool_calls") or []
    if not content and not tool_calls:
        raise BrokerError("provider returned empty tool-aware response")
    return {"message": message, "finish_reason": str(choice.get("finish_reason") or ("tool_calls" if tool_calls else "stop"))}


def _groq(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    return _openai_compatible("https://api.groq.com/openai/v1/chat/completions", prompt, _provider_model(provider), secrets["GROQ_API_KEY"])


def _groq_chat(messages: list[dict], tools: list[dict], provider: dict, secrets: dict[str, str], tool_choice=None) -> dict:
    return _openai_chat(
        "https://api.groq.com/openai/v1/chat/completions",
        messages,
        tools,
        _provider_model(provider),
        secrets["GROQ_API_KEY"],
        tool_choice=tool_choice,
    )


def _openrouter(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    return _openai_compatible("https://openrouter.ai/api/v1/chat/completions", prompt, _provider_model(provider), secrets["OPENROUTER_API_KEY"])


def _openrouter_chat(messages: list[dict], tools: list[dict], provider: dict, secrets: dict[str, str], tool_choice=None) -> dict:
    return _openai_chat(
        "https://openrouter.ai/api/v1/chat/completions",
        messages,
        tools,
        _provider_model(provider),
        secrets["OPENROUTER_API_KEY"],
        tool_choice=tool_choice,
    )


def _cloudflare(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    account = secrets["CLOUDFLARE_ACCOUNT_ID"]
    model = _provider_model(provider)
    url = "https://api.cloudflare.com/client/v4/accounts/" + urllib.parse.quote(account, safe="") + "/ai/run/" + model
    result = _post_json(url, {"messages": [{"role": "user", "content": prompt}], "temperature": 0}, headers={"Authorization": f"Bearer {secrets['CLOUDFLARE_API_TOKEN']}"})
    if result.get("success") is False:
        raise BrokerError("cloudflare returned unsuccessful response")
    payload = result.get("result")
    text = str((payload or {}).get("response", "") if isinstance(payload, dict) else payload or "").strip()
    if not text:
        raise BrokerError("cloudflare returned empty response")
    return text


def _invoke(provider: dict, prompt: str, secrets: dict[str, str]) -> str:
    pid = provider["id"]
    if pid == "ollama":
        return _ollama(prompt, _provider_model(provider))
    if pid == "gemini":
        return _gemini(prompt, provider, secrets)
    if pid == "groq":
        return _groq(prompt, provider, secrets)
    if pid == "openrouter":
        return _openrouter(prompt, provider, secrets)
    if pid == "cloudflare":
        return _cloudflare(prompt, provider, secrets)
    raise BrokerError(f"provider {pid} is not a direct inference provider")


def candidates(*, privacy: str = "normal", task_class: str = "normal") -> tuple[list[dict], list[dict]]:
    policy = ROUTER.load_policy(POLICY_PATH)
    secret_names = ROUTER.load_secret_names(SECRETS_PATH)
    adapters = {"local-builder"} if privacy == "local-only" else {"direct-cloud"}
    return ROUTER.eligible_providers(policy, task_class, secret_names, privacy=privacy, available_adapters=adapters)


def chat(messages: list[dict], *, tools: list[dict] | None = None, tool_choice=None, privacy: str = "normal", task_class: str = "normal") -> dict:
    """Preserve OpenAI tool-calling semantics for agentic cloud-safe requests."""
    if privacy != "normal":
        raise BrokerError("tool-enabled private inference is not permitted")
    cloud_eligible, considered = candidates(privacy=privacy, task_class=task_class)
    local_eligible, local_considered = candidates(privacy="local-only", task_class=task_class)
    eligible = []
    seen: set[str] = set()
    for provider in [*local_eligible, *cloud_eligible]:
        pid = str(provider.get("id") or "")
        if pid in {"ollama", "gemini", "groq", "openrouter"} and pid not in seen:
            eligible.append(provider)
            seen.add(pid)
    considered = [*local_considered, *considered]
    if not eligible:
        raise BrokerError("no eligible tool-capable provider")
    secrets = _strict_env(SECRETS_PATH)
    failures: list[str] = []
    for provider in eligible:
        pid = provider["id"]
        try:
            if pid == "ollama":
                response = _ollama_chat(messages, tools or [], provider, tool_choice=tool_choice)
            elif pid == "gemini":
                response = _gemini_chat(messages, tools or [], provider, secrets, tool_choice=tool_choice)
            elif pid == "groq":
                response = _groq_chat(messages, tools or [], provider, secrets, tool_choice=tool_choice)
            elif pid == "openrouter":
                response = _openrouter_chat(messages, tools or [], provider, secrets, tool_choice=tool_choice)
            else:
                continue
            return {
                "provider": pid,
                "model": _provider_model(provider),
                "privacy": privacy,
                "considered": considered,
                **response,
            }
        except (BrokerError, KeyError) as exc:
            detail = " ".join(str(exc).split())
            if len(detail) > 300:
                detail = detail[:297] + "..."
            failures.append(f"{pid}:{type(exc).__name__}:{detail}")
    raise BrokerError("tool-capable providers exhausted: " + " | ".join(failures))


def generate(prompt: str, *, privacy: str = "normal", task_class: str = "normal", force_provider: str | None = None) -> dict:
    if privacy not in {"normal", "local-only"}:
        raise BrokerError("unsupported privacy class")
    prompt = str(prompt)
    if not prompt.strip():
        raise BrokerError("prompt required")
    eligible, considered = candidates(privacy=privacy, task_class=task_class)
    if force_provider:
        eligible = [p for p in eligible if p.get("id") == force_provider]
    if not eligible:
        raise BrokerError("no eligible inference provider")
    secrets = _strict_env(SECRETS_PATH)
    failures: list[str] = []
    for provider in eligible:
        pid = provider["id"]
        try:
            text = _invoke(provider, prompt, secrets)
            return {"provider": pid, "model": _provider_model(provider), "privacy": privacy, "text": text, "considered": considered}
        except (BrokerError, KeyError) as exc:
            failures.append(f"{pid}:{type(exc).__name__}")
            if privacy == "local-only":
                break
    raise BrokerError("eligible providers exhausted: " + ",".join(failures))
