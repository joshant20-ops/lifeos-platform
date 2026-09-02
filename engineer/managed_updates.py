#!/usr/bin/env python3
"""Fail-closed planning and evidence contract for managed component updates.

This module deliberately has no Docker, SSH, HA, or network authority. It turns
sanitised release observations and deterministic check results into a review
packet. Pi5 remains the only runtime executor and canonical Git writer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE = ("detect", "review", "test", "deploy_one", "regress", "accept_or_rollback", "evidence")
REGRESSION_CHECKS = (
    "ha_api", "predbat_plan", "predbat_entities", "energy_telemetry",
    "power_signs", "predbat_sanity_service", "forecast_services",
    "tariff_provenance", "power_down_assurance", "mqtt", "lifeos_energy",
    "systemd_failures", "git_runtime_alignment", "secret_scan",
)
PRE_UPDATE_CHECKS = (
    "installed_candidate_versions", "container_health_start_time", "git_alignment",
    "systemd_units", "ha_api", "predbat_status", "energy_telemetry",
    "predbat_sanity", "power_down_assurance", "mqtt", "backup", "rollback_plan",
)
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ContractError(ValueError):
    pass


def _version(value: str) -> tuple[int, int, int]:
    match = SEMVER.match(value)
    if not match:
        raise ContractError(f"invalid semantic version: {value}")
    return tuple(map(int, match.groups()))


def load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text())
    if policy.get("mode") != "shadow" or not policy.get("targets"):
        raise ContractError("policy must start in shadow mode with an allow-list")
    return policy


def coalesce(releases: list[dict[str, Any]]) -> dict[str, Any]:
    """Select newest stable semantic version, independent of input ordering."""
    eligible = [r for r in releases if not r.get("prerelease", False)]
    if not eligible:
        raise ContractError("no stable candidate release")
    return max(eligible, key=lambda r: _version(str(r["version"])))


def classify_risk(target: str, installed: str, candidate: dict[str, Any], terms: list[str]) -> tuple[str, list[str]]:
    old, new = _version(installed), _version(str(candidate["version"]))
    reasons: list[str] = []
    if new <= old:
        reasons.append("candidate_not_newer")
    notes = str(candidate.get("release_notes", "")).lower()
    reasons.extend(f"release_term:{term}" for term in terms if term.lower() in notes)
    if target == "home-assistant-core" and new[0] != old[0]:
        reasons.append("home_assistant_major_change")
    return ("escalate" if reasons else "routine", sorted(set(reasons)))


def _required_checks(results: dict[str, Any], required: tuple[str, ...], stage: str) -> None:
    missing = sorted(set(required) - set(results))
    if missing:
        raise ContractError(f"{stage} evidence missing: {','.join(missing)}")


def disposition(regression: dict[str, str], rollback_safe: bool) -> tuple[str, bool]:
    _required_checks(regression, REGRESSION_CHECKS, "regression")
    values = {str(regression[name]).upper() for name in REGRESSION_CHECKS}
    if values - {"PASS", "WATCH", "FAIL"}:
        raise ContractError("regression results must be PASS, WATCH, or FAIL")
    if "FAIL" in values:
        return ("ROLLBACK_REQUIRED" if rollback_safe else "ESCALATE_ROLLBACK_UNPROVEN", False)
    if "WATCH" in values:
        return "WATCH", False
    return "ACCEPTED", False


def prove_rollback(observation: dict[str, Any], installed_digest: str) -> None:
    """Require deterministic evidence that the previous baseline was restored."""
    proof = observation.get("rollback_proof")
    if not isinstance(proof, dict):
        raise ContractError("rollback proof is required before reporting ROLLED_BACK")
    if proof.get("restored_digest") != installed_digest:
        raise ContractError("rollback restored digest does not match pre-update digest")
    regression = proof.get("regression")
    if not isinstance(regression, dict):
        raise ContractError("rollback regression evidence is required")
    _required_checks(regression, REGRESSION_CHECKS, "rollback regression")
    values = {str(regression[name]).upper() for name in REGRESSION_CHECKS}
    if values != {"PASS"}:
        raise ContractError("rollback regression must pass every mandatory check")


def build_packet(policy: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    target = str(observation.get("target", ""))
    if target not in policy["targets"] or not policy["targets"][target].get("enabled"):
        raise ContractError(f"target not allow-listed: {target}")
    candidates = observation.get("releases", [])
    candidate = coalesce(candidates)
    installed = str(observation["installed_version"])
    installed_digest = str(observation.get("installed_digest", ""))
    candidate_digest = str(candidate.get("digest", ""))
    if not DIGEST.match(installed_digest) or not DIGEST.match(candidate_digest):
        raise ContractError("installed and candidate sha256 digests are required")
    risk, reasons = classify_risk(target, installed, candidate, policy["targets"][target]["risk_terms"])
    pre = observation.get("pre_update", {})
    _required_checks(pre, PRE_UPDATE_CHECKS, "pre-update")
    regression = observation.get("regression")
    final, rollback_executed = ("SHADOW_REVIEW", False)
    if regression is not None:
        final, rollback_executed = disposition(regression, bool(observation.get("rollback_safe", False)))
    if observation.get("rollback_proof") is not None:
        if final != "ROLLBACK_REQUIRED":
            raise ContractError("rollback proof is only valid after a failed regression")
        prove_rollback(observation, installed_digest)
        final, rollback_executed = "ROLLED_BACK", True
    source = str(candidate.get("source", ""))
    if not source.startswith("https://"):
        raise ContractError("candidate source must be an HTTPS release URL")
    packet = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": policy["mode"],
        "pipeline": list(PIPELINE),
        "target": target,
        "installed_version": installed,
        "installed_digest": installed_digest,
        "candidate_version": candidate["version"],
        "candidate_source": source,
        "candidate_digest": candidate_digest,
        "coalesced_release_count": len(candidates),
        "risk": risk,
        "risk_reasons": reasons,
        "automatic_deploy_allowed": False,
        "one_component_only": True,
        "pre_update": pre,
        "regression": regression,
        "rollback_proof": observation.get("rollback_proof"),
        "final_disposition": final,
        "rollback_executed": rollback_executed,
        "control_writes_permitted": False,
        "private_content_included": False,
    }
    canonical = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    packet["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    return packet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("managed_updates.json"))
    parser.add_argument("--observation", type=Path, required=True, help="sanitised JSON; never private HA state")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    packet = build_packet(load_policy(args.policy), json.loads(args.observation.read_text()))
    rendered = json.dumps(packet, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
