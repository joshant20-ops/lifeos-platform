import copy
import json
from pathlib import Path

import pytest

from engineer.managed_updates import ContractError, REGRESSION_CHECKS, build_packet, load_policy

ROOT = Path(__file__).parents[1]
POLICY = load_policy(ROOT / "engineer/managed_updates.json")


def observation(target="predbat"):
    from engineer.managed_updates import PRE_UPDATE_CHECKS
    return {
        "target": target,
        "installed_version": "8.0.0",
        "installed_digest": "sha256:" + "0" * 64,
        "releases": [
            {"version": "8.0.1", "digest": "sha256:" + "1" * 64, "source": "https://example.invalid/releases/8.0.1", "release_notes": "fix"},
            {"version": "8.0.3", "digest": "sha256:" + "3" * 64, "source": "https://example.invalid/releases/8.0.3", "release_notes": "latest fix"},
            {"version": "8.0.2", "digest": "sha256:" + "2" * 64, "source": "https://example.invalid/releases/8.0.2", "release_notes": "fix"},
        ],
        "pre_update": {name: "PASS" for name in PRE_UPDATE_CHECKS},
    }


def test_coalesces_rapid_releases_and_stays_shadow_only():
    packet = build_packet(POLICY, observation())
    assert packet["candidate_version"] == "8.0.3"
    assert packet["coalesced_release_count"] == 3
    assert packet["final_disposition"] == "SHADOW_REVIEW"
    assert packet["automatic_deploy_allowed"] is False
    assert packet["control_writes_permitted"] is False


def test_unknown_target_and_incomplete_evidence_fail_closed():
    bad = observation("random-container")
    with pytest.raises(ContractError, match="not allow-listed"):
        build_packet(POLICY, bad)


def test_mutable_tag_without_digests_fails_closed():
    bad = observation()
    bad["releases"][1].pop("digest")
    with pytest.raises(ContractError, match="digests"):
        build_packet(POLICY, bad)
    bad = observation()
    del bad["pre_update"]["backup"]
    with pytest.raises(ContractError, match="backup"):
        build_packet(POLICY, bad)


def test_risky_release_escalates():
    item = observation()
    item["releases"][-2]["release_notes"] = "Changes battery control entity semantics"
    packet = build_packet(POLICY, item)
    assert packet["risk"] == "escalate"
    assert "release_term:battery" in packet["risk_reasons"]


def test_deliberate_regression_failure_proves_safe_rollback_decision():
    item = observation()
    item["rollback_safe"] = True
    item["regression"] = {name: "PASS" for name in REGRESSION_CHECKS}
    item["regression"]["predbat_plan"] = "FAIL"
    packet = build_packet(POLICY, item)
    assert packet["final_disposition"] == "ROLLED_BACK"
    assert packet["rollback_executed"] is True


def test_failed_regression_without_proven_rollback_escalates():
    item = observation()
    item["regression"] = {name: "PASS" for name in REGRESSION_CHECKS}
    item["regression"]["ha_api"] = "FAIL"
    packet = build_packet(POLICY, item)
    assert packet["final_disposition"] == "ESCALATE_ROLLBACK_UNPROVEN"
    assert packet["rollback_executed"] is False


def test_managed_compose_services_are_excluded_from_watchtower():
    for rel in ("predbat", "homeassistant"):
        for tree in ("ansible/desired/compose", "homelab/live/opt/stacks"):
            text = (ROOT / tree / rel / "docker-compose.yml").read_text()
            assert "com.centurylinklabs.watchtower.enable=false" in text
