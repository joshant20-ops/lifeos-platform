import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_private_domains_fail_closed_and_forbid_cloud_fallback():
    policy = json.loads((ROOT / "governor/privacy-domain-policy.json").read_text())
    assert policy["schema_version"] == 1
    assert policy["fail_closed"] is True
    for domain in ("personal-administration", "finance-assets"):
        rule = policy["domains"][domain]
        assert rule["privacy"] == "local-only"
        assert rule["cloud_fallback"] is False
        assert rule["public_reference_queries"] == "sanitized-general-question-only"


def test_existing_router_contract_for_local_only_is_fail_closed():
    source = (ROOT / "engineer/provider_router.py").read_text()
    assert 'if privacy == "local-only"' in source
    assert 'return boundary in {"local", "deterministic"}' in source


def test_existing_agent_has_no_cloud_fallback_for_local_only_jobs():
    source = (ROOT / "governor/autonomous_agent.py").read_text()
    assert 'route = "local" if job.get("privacy") == "local-only" else "normal"' in source
    assert 'if job["privacy"] == "local-only" and handoff.get("_builder_route") != "local"' in source
