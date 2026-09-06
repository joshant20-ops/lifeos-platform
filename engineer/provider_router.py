#!/usr/bin/env python3
"""Policy-only AI provider routing for LifeOS Engineer.

The router never calls a model and never receives secret values.  It chooses the
cheapest sufficiently capable provider that is allowed by privacy policy and is
actually runnable by the available adapter set.  Execution remains a separate
Engineer/Governor concern.
"""
from __future__ import annotations

import json
import stat
import time
from pathlib import Path


class PolicyError(RuntimeError):
    pass


COST_RANK = {
    "deterministic": 0,
    "local": 1,
    "free": 2,
    "free-tier": 2,
    "free-models-only": 2,
    "scarce": 3,
    "paid": 4,
}


def load_policy(path: Path) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 3:
        raise PolicyError("policy must be schema v3")
    routing = policy.get("routing", {})
    if routing.get("strategy") != "cheapest-capable":
        raise PolicyError("routing strategy must be cheapest-capable")
    if not isinstance(policy.get("providers"), list) or not policy["providers"]:
        raise PolicyError("providers are required")
    return policy


def load_secret_names(path: Path | None) -> set[str]:
    """Read credential *names* from a strict env file; never return values."""
    if path is None or not path.exists():
        return set()
    if stat.S_IMODE(path.stat().st_mode) != 0o600 or not path.is_file() or path.is_symlink():
        raise PolicyError("secrets file must be a regular, non-symlink mode-0600 file")
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        if not sep or not name.replace("_", "").isalnum() or not name[0].isalpha():
            raise PolicyError("invalid secrets file assignment")
        if value:
            names.add(name)
    return names


def _credentials(provider: dict) -> list[str]:
    value = provider.get("credentials")
    if value is None:
        one = provider.get("credential")
        return [one] if one else []
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise PolicyError(f"provider {provider.get('id')} has invalid credentials")
    return value


def _minimum_capability(policy: dict, task_class: str) -> int:
    table = policy.get("routing", {}).get("minimum_capability", {})
    return int(table.get(task_class, table.get("default", 1)))


def _privacy_allowed(provider: dict, privacy: str) -> bool:
    boundary = provider.get("privacy", "sanitized-cloud")
    if privacy == "local-only":
        return boundary in {"local", "deterministic"}
    return boundary in {"local", "deterministic", "sanitized-cloud"}


def eligible_providers(
    policy: dict,
    task_class: str,
    secret_names: set[str],
    cooldowns=None,
    now=None,
    *,
    privacy: str = "normal",
    available_adapters: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return eligible providers in score order plus redacted routing evidence."""
    now = time.time() if now is None else now
    cooldowns = cooldowns or {}
    minimum = _minimum_capability(policy, task_class)
    allow_paid = bool(policy.get("routing", {}).get("allow_paid_fallback", False))
    considered: list[dict] = []
    eligible: list[dict] = []

    for index, provider in enumerate(policy["providers"]):
        if task_class not in provider.get("task_classes", []):
            continue
        pid = provider["id"]
        status = "AVAILABLE"
        cost = provider.get("cost", "paid")
        adapter = provider.get("adapter", pid)
        capability = int(provider.get("capability", 1))
        needed_credentials = _credentials(provider)

        if not _privacy_allowed(provider, privacy):
            status = "PRIVACY_FORBIDDEN"
        elif capability < minimum:
            status = "CAPABILITY_INSUFFICIENT"
        elif cost == "paid" and not allow_paid:
            status = "PAID_FORBIDDEN"
        elif available_adapters is not None and adapter not in available_adapters:
            status = "ADAPTER_UNAVAILABLE"
        elif any(name not in secret_names for name in needed_credentials):
            status = "CREDENTIAL_REQUIRED"
        elif cooldowns.get(pid, 0) > now:
            status = "COOLDOWN"

        item = {
            "provider": pid,
            "status": status,
            "adapter": adapter,
            "capability": capability,
            "cost": cost,
        }
        considered.append(item)
        if status == "AVAILABLE":
            candidate = dict(provider)
            candidate["_policy_index"] = index
            eligible.append(candidate)

    # Cost is the primary objective, but only after minimum capability/privacy
    # constraints are met.  Explicit priority lets policy prefer a stronger or
    # faster provider among providers with the same spend class.
    eligible.sort(
        key=lambda p: (
            COST_RANK.get(p.get("cost", "paid"), 99),
            int(p.get("priority", 100)),
            -int(p.get("capability", 1)),
            p["_policy_index"],
        )
    )
    for item in eligible:
        item.pop("_policy_index", None)
    return eligible, considered


def route(
    policy: dict,
    task_class: str,
    secret_names: set[str],
    cooldowns=None,
    now=None,
    *,
    privacy: str = "normal",
    available_adapters: set[str] | None = None,
) -> dict:
    providers, considered = eligible_providers(
        policy,
        task_class,
        secret_names,
        cooldowns,
        now,
        privacy=privacy,
        available_adapters=available_adapters,
    )
    selected = providers[0] if providers else None
    return {
        "selected_provider": selected["id"] if selected else None,
        "selected_role": selected.get("role") if selected else None,
        "selected_adapter": selected.get("adapter") if selected else None,
        "task_class": task_class,
        "privacy": privacy,
        "considered": considered,
        "fail_closed": selected is None,
        "max_attempts": int(policy["routing"].get("max_attempts_per_provider", 1)),
        "cooldown_seconds": int(policy["routing"].get("cooldown_seconds", 900)),
    }


def credential_environment(path: Path | None, allowed_names: set[str]) -> dict[str, str]:
    """Load only explicitly selected credentials for a model subprocess."""
    if path is None:
        return {}
    load_secret_names(path)
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        if sep and name in allowed_names and value:
            result[name] = value
    return result


def openhands_environment(provider: dict, secrets_path: Path | None) -> dict[str, str]:
    """Translate a selected provider to current OpenHands environment variables."""
    model = provider.get("openhands_model")
    if not model:
        raise PolicyError(f"provider {provider['id']} has no OpenHands model")
    required = set(_credentials(provider))
    native = credential_environment(secrets_path, required)
    if required - set(native):
        raise PolicyError(f"provider {provider['id']} credential unavailable")
    result = {"LIFEOS_PROVIDER": provider["id"], "LLM_MODEL": model}
    if len(required) == 1:
        value = native[next(iter(required))]
        result["LLM_API_KEY"] = value
    result.update(native)
    base_url = provider.get("llm_base_url")
    if base_url:
        result["LLM_BASE_URL"] = str(base_url)
    return result
