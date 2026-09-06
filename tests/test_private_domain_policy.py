import importlib.machinery
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "governor/autonomous_agent.py"
POLICY = ROOT / "governor/privacy-domain-policy.json"


def load_agent(tmp_path):
    previous_state = os.environ.get("LIFEOS_AGENT_STATE")
    previous_policy = os.environ.get("LIFEOS_PRIVACY_DOMAIN_POLICY")
    os.environ["LIFEOS_AGENT_STATE"] = str(tmp_path / "state")
    os.environ["LIFEOS_PRIVACY_DOMAIN_POLICY"] = str(POLICY)
    try:
        return importlib.machinery.SourceFileLoader(
            f"private_domain_policy_{tmp_path.name}", str(SOURCE)
        ).load_module()
    finally:
        if previous_state is None:
            os.environ.pop("LIFEOS_AGENT_STATE", None)
        else:
            os.environ["LIFEOS_AGENT_STATE"] = previous_state
        if previous_policy is None:
            os.environ.pop("LIFEOS_PRIVACY_DOMAIN_POLICY", None)
        else:
            os.environ["LIFEOS_PRIVACY_DOMAIN_POLICY"] = previous_policy


def test_private_domains_fail_closed_and_forbid_cloud_fallback():
    policy = json.loads(POLICY.read_text())
    assert policy["schema_version"] == 1
    assert policy["fail_closed"] is True
    for domain in ("personal-administration", "finance-assets"):
        rule = policy["domains"][domain]
        assert rule["privacy"] == "local-only"
        assert rule["cloud_fallback"] is False
        assert rule["request_terms"]
        assert rule["public_reference_queries"] == "sanitized-general-question-only"


def test_explicit_private_domain_is_local_only(tmp_path):
    agent = load_agent(tmp_path)
    assert agent.classify_privacy(
        "Summarize upcoming appointments", domain="personal-administration"
    ) == "local-only"
    assert agent.classify_privacy(
        "Prepare the monthly overview", domain="finance-assets"
    ) == "local-only"


def test_private_domain_terms_are_classified_without_metadata(tmp_path):
    agent = load_agent(tmp_path)
    assert agent.classify_privacy("Summarize my calendar for tomorrow") == "local-only"
    assert agent.classify_privacy("Review my vehicle costs this month") == "local-only"


def test_dispatch_normal_cannot_downgrade_private_request(tmp_path):
    agent = load_agent(tmp_path)
    job = agent.new_job("Check my bank statements", dispatch_builder="normal")
    assert job["privacy"] == "local-only"
    assert agent.builder_route(job)[0] == "local"


def test_unknown_explicit_domain_fails_closed(tmp_path):
    agent = load_agent(tmp_path)
    assert agent.classify_privacy("Handle this", domain="unknown-private-domain") == "local-only"
