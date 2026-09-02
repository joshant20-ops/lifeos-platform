import importlib.machinery
import os
from pathlib import Path


SOURCE = Path("governor/autonomous_agent.py")


def load_agent(tmp_path):
    previous = os.environ.get("LIFEOS_AGENT_STATE")
    os.environ["LIFEOS_AGENT_STATE"] = str(tmp_path / "state")
    try:
        return importlib.machinery.SourceFileLoader(
            f"privacy_classifier_{tmp_path.name}", str(SOURCE)
        ).load_module()
    finally:
        if previous is None:
            os.environ.pop("LIFEOS_AGENT_STATE", None)
        else:
            os.environ["LIFEOS_AGENT_STATE"] = previous


def test_ordinary_engineering_code_and_documentation_are_normal(tmp_path):
    agent = load_agent(tmp_path)
    request = (
        "Perform a read-only Engineer audit of repository code and documentation "
        "for consistency using only cloud-safe repository content."
    )
    assert agent.classify_privacy(request) == "normal"


def test_genuinely_sensitive_requests_remain_local_only(tmp_path):
    agent = load_agent(tmp_path)
    sensitive_requests = (
        "Review my private documents",
        "Summarize personal data records",
        "Check my bank statements",
        "Inspect medical information",
    )
    assert all(agent.classify_privacy(text) == "local-only" for text in sensitive_requests)
