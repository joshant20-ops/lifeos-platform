import importlib.machinery
import importlib.util
import pathlib
from unittest import mock

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BROKER = ROOT / "homelab/live/usr/local/sbin/lifeos-root-broker"
AGENT = ROOT / "governor/autonomous_agent.py"


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_deployments_are_fixed_declarative_manifests():
    broker = load(BROKER, "bounded_broker")
    assert set(broker.DEPLOYMENT_SPECS) == {
        "deploy-engineer-runtime", "deploy-autonomous-agent", "deploy-backlog-runner"
    }
    for spec in broker.DEPLOYMENT_SPECS.values():
        assert spec["files"]
        for source, destination in spec["files"]:
            assert not pathlib.PurePosixPath(source).is_absolute()
            assert ".." not in pathlib.PurePosixPath(source).parts
            assert destination.is_absolute()
    assert broker.DEPLOYMENT_SPECS["deploy-backlog-runner"]["must_remain_inactive"] == (
        "lifeos-backlog-runner.timer",
    )


@pytest.mark.parametrize("operation", ["deploy-autonomous-agent", "deploy-backlog-runner"])
@pytest.mark.parametrize("field", ["command", "source", "destination", "unit", "environment", "args"])
def test_new_deployments_reject_caller_selected_capabilities(operation, field):
    broker = load(BROKER, f"bounded_{operation}_{field}")
    with mock.patch.object(broker, "reply"), pytest.raises(SystemExit):
        broker.deploy_bounded_operation(
            {"operation": operation, "job_id": "job-1", "target": "pi5", field: "../../evil"},
            "pi5", operation, broker.DEPLOYMENT_SPECS[operation],
        )


def test_governor_maps_only_exact_deployment_intents(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_AGENT_STATE", str(tmp_path))
    agent = load(AGENT, "bounded_agent")
    assert agent.DEPLOYMENT_OPERATIONS == {
        "deploy-engineer-runtime", "deploy-autonomous-agent", "deploy-backlog-runner"
    }
    for intent in ("restart-approved-unit", "deploy-backlog-runner;id", "../../bin/sh", ""):
        assert agent.request_bounded_deployment("job-1", intent)["status"] == "REJECTED"
    handoff, _ = agent.parse_handoff("DEPLOYMENT_OPERATION=deploy-backlog-runner\n")
    assert handoff["deployment_operation"] == "deploy-backlog-runner"


def test_restart_allowlist_rejects_arbitrary_unit():
    broker = load(BROKER, "restart_broker")
    with mock.patch.object(broker, "reply"), pytest.raises(SystemExit):
        broker.restart_approved_unit(
            {"operation": "restart-approved-unit", "job_id": "job-1", "target": "pi5", "unit": "ssh.service"},
            "pi5",
        )
