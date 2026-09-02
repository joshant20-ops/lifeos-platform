#!/usr/bin/env python3
"""Zero-spend, provider-agnostic routing for the OpenHands Engineer worker."""
from __future__ import annotations
import json, stat, time
from pathlib import Path

class PolicyError(RuntimeError): pass

def load_policy(path: Path) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 2 or policy.get("routing", {}).get("allow_paid_fallback") is not False:
        raise PolicyError("policy must be schema v2 with paid fallback disabled")
    return policy

def load_secret_names(path: Path | None) -> set[str]:
    if path is None or not path.exists(): return set()
    if stat.S_IMODE(path.stat().st_mode) != 0o600 or not path.is_file() or path.is_symlink():
        raise PolicyError("secrets file must be a regular, non-symlink mode-0600 file")
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        if line.startswith("export "): line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        if not sep or not name.replace("_", "").isalnum() or not name[0].isalpha():
            raise PolicyError("invalid secrets file assignment")
        if value: names.add(name)
    return names

def route(policy: dict, task_class: str, secret_names: set[str], cooldowns=None, now=None) -> dict:
    now, cooldowns = time.time() if now is None else now, cooldowns or {}
    considered, selected = [], None
    for provider in policy["providers"]:
        if task_class not in provider["task_classes"]: continue
        status = "AVAILABLE"
        if provider["cost"] not in {"free", "free-tier", "free-models-only", "local", "scarce"}: status = "PAID_FORBIDDEN"
        elif provider.get("credential") and provider["credential"] not in secret_names: status = "CREDENTIAL_REQUIRED"
        elif cooldowns.get(provider["id"], 0) > now: status = "COOLDOWN"
        considered.append({"provider": provider["id"], "status": status})
        if selected is None and status == "AVAILABLE": selected = provider
    return {"selected_provider": selected["id"] if selected else None, "selected_role": selected["role"] if selected else None,
            "task_class": task_class, "considered": considered, "fail_closed": selected is None,
            "max_attempts": policy["routing"]["max_attempts_per_provider"], "cooldown_seconds": policy["routing"]["cooldown_seconds"]}

def eligible_providers(policy: dict, task_class: str, secret_names: set[str], cooldowns=None, now=None) -> tuple[list[dict], list[dict]]:
    """Return eligible providers in policy order plus redacted routing evidence."""
    decision = route(policy, task_class, secret_names, cooldowns, now)
    statuses = {item["provider"]: item["status"] for item in decision["considered"]}
    providers = [item for item in policy["providers"] if statuses.get(item["id"]) == "AVAILABLE"]
    return providers, decision["considered"]

def openhands_environment(provider: dict, secrets_path: Path | None) -> dict[str, str]:
    """Translate governor policy to OpenHands/LiteLLM variables without logging values."""
    model = provider.get("openhands_model")
    if not model:
        raise PolicyError(f"provider {provider['id']} has no OpenHands model")
    allowed = {provider["credential"]} if provider.get("credential") else set()
    native = credential_environment(secrets_path, allowed)
    result = {"LIFEOS_PROVIDER": provider["id"], "LLM_MODEL": model}
    if allowed:
        result["LLM_API_KEY"] = native[provider["credential"]]
        result.update(native)
    return result

def credential_environment(path: Path | None, allowed_names: set[str]) -> dict[str, str]:
    if path is None: return {}
    load_secret_names(path)
    result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "): line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        if sep and name in allowed_names and value: result[name] = value
    return result
