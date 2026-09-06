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


class BrokerError(RuntimeError):
    pass


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
    """Read a mode-0600 regular env file without ever logging values."""
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
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
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
        return False
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
    result = _post_json(
        OLLAMA_URL,
        {"model": model, "prompt": prompt, "stream": False, "keep_alive": "30m"},
        timeout=HTTP_TIMEOUT,
    )
    text = str(result.get("response", "")).strip()
    if not text:
        raise BrokerError("ollama returned empty response")
    return text


def _ollama(prompt: str, model: str) -> str:
    try:
        return _ollama_once(prompt, model)
    except BrokerError as first:
        if not _wake_local_ai():
            raise first
        deadline = time.monotonic() + WAKE_TIMEOUT
        last: Exception = first
        while time.monotonic() < deadline:
            time.sleep(3)
            try:
                return _ollama_once(prompt, model)
            except BrokerError as exc:
                last = exc
        raise BrokerError("local AI did not become ready after Wake-on-LAN") from last


def _gemini(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    key = secrets["GEMINI_API_KEY"]
    model = _provider_model(provider)
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model, safe="-._")
        + ":generateContent?key="
        + urllib.parse.quote(key, safe="")
    )
    result = _post_json(url, {"contents": [{"parts": [{"text": prompt}]}]})
    candidates = result.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise BrokerError("gemini returned empty response")
    return text


def _openai_compatible(url: str, prompt: str, model: str, token: str) -> str:
    result = _post_json(
        url,
        {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    choices = result.get("choices") or []
    text = str(((choices[0].get("message") or {}).get("content") or "") if choices else "").strip()
    if not text:
        raise BrokerError("provider returned empty response")
    return text


def _groq(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    return _openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions",
        prompt,
        _provider_model(provider),
        secrets["GROQ_API_KEY"],
    )


def _openrouter(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    return _openai_compatible(
        "https://openrouter.ai/api/v1/chat/completions",
        prompt,
        _provider_model(provider),
        secrets["OPENROUTER_API_KEY"],
    )


def _cloudflare(prompt: str, provider: dict, secrets: dict[str, str]) -> str:
    account = secrets["CLOUDFLARE_ACCOUNT_ID"]
    model = _provider_model(provider)
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        + urllib.parse.quote(account, safe="")
        + "/ai/run/"
        + model
    )
    result = _post_json(
        url,
        {"messages": [{"role": "user", "content": prompt}], "temperature": 0},
        headers={"Authorization": f"Bearer {secrets['CLOUDFLARE_API_TOKEN']}"},
    )
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
    return ROUTER.eligible_providers(
        policy,
        task_class,
        secret_names,
        privacy=privacy,
        available_adapters=adapters,
    )


def generate(
    prompt: str,
    *,
    privacy: str = "normal",
    task_class: str = "normal",
    force_provider: str | None = None,
) -> dict:
    """Route and execute one inference request.

    local-only jobs can never obtain a cloud candidate. Normal jobs use direct
    cloud providers and therefore do not wake Engineer/Z97 merely for inference.
    """
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
            return {
                "provider": pid,
                "model": _provider_model(provider),
                "privacy": privacy,
                "text": text,
                "considered": considered,
            }
        except (BrokerError, KeyError) as exc:
            failures.append(f"{pid}:{type(exc).__name__}")
            if privacy == "local-only":
                break
    raise BrokerError("eligible providers exhausted: " + ",".join(failures))
