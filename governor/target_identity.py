#!/usr/bin/env python3
"""Fail-closed access to the LifeOS privileged-operation target identity."""

import json
import pathlib


IDENTITY_PATH = pathlib.Path("/etc/lifeos-control/identity.json")


class TargetIdentityError(RuntimeError):
    """The authoritative target identity cannot safely be used."""


def load_target_id(identity_path=None):
    """Return the authoritative non-empty target_id or raise."""
    path = IDENTITY_PATH if identity_path is None else pathlib.Path(identity_path)
    try:
        identity = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TargetIdentityError("LifeOS target identity unavailable or malformed") from exc
    if not isinstance(identity, dict):
        raise TargetIdentityError("LifeOS target identity must be an object")
    target_id = identity.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        raise TargetIdentityError("LifeOS target_id must be a non-empty string")
    return target_id
