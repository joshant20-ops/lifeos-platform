import importlib.machinery
import importlib.util
import json
import pathlib
from unittest import mock

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BROKER_PATH = ROOT / "homelab/live/usr/local/sbin/lifeos-root-broker"
AGENT_PATH = ROOT / "governor/autonomous_agent.py"


def load_broker():
    loader = importlib.machinery.SourceFileLoader("lifeos_root_broker_test", str(BROKER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def approval(job="job-1"):
    return {
        "schema_version": 1,
        "operation": "deploy-engineer-runtime",
        "job_id": job,
        "target": "pi5",
        "source_commit": "a" * 40,
        "source_hashes": {"governor/autonomous_agent.py": "b" * 64, "governor/engineer_backend.py": "c" * 64},
        "publication_verified": True,
        "independent_verifier": {"verdict": "PASS", "evidence_id": "verifier-1"},
        "protected_policy": {"verdict": "PASS", "evidence_id": "policy-1"},
        "approved_at": "2026-09-01T00:00:00Z",
    }


def test_request_cannot_supply_command_path_destination_unit_or_hash():
    broker = load_broker()
    for extra in ("command", "path", "destination", "unit", "args", "source_hashes"):
        with mock.patch.object(broker, "reply"), pytest.raises(SystemExit):
            broker.deploy_engineer_runtime(
                {"operation": "deploy-engineer-runtime", "job_id": "job-1", "target": "pi5", extra: "evil"},
                "pi5",
            )


def test_agent_request_is_bounded_and_only_runs_after_verifier_pass():
    text = AGENT_PATH.read_text()
    function = text[text.index("def request_engineer_runtime_deployment"):text.index("def now()")]
    assert '"operation": "deploy-engineer-runtime"' in function
    for forbidden in ("command", "destination", "unit", "source_hashes", "args"):
        assert f'"{forbidden}"' not in function
    pass_branch = text[text.index('if v == "PASS":'):text.index('if v == "BLOCKED":')]
    assert "request_engineer_runtime_deployment" in pass_branch


def test_approval_fails_closed_on_verifier_policy_and_hash_shape(tmp_path):
    broker = load_broker()
    broker.DEPLOY_APPROVALS = tmp_path
    path = tmp_path / "job-1.json"
    for mutate in (
        lambda item: item["independent_verifier"].update(verdict="RETRY"),
        lambda item: item["protected_policy"].update(verdict="FAIL"),
        lambda item: item["source_hashes"].update({"unexpected.py": "d" * 64}),
    ):
        item = approval()
        mutate(item)
        path.write_text(json.dumps(item))
        path.chmod(0o600)
        with mock.patch.object(broker, "require_safe_regular"), mock.patch.object(broker, "reply"), pytest.raises(SystemExit):
            broker.load_deploy_approval("job-1", "pi5")


def run_transaction(tmp_path, health_results):
    broker = load_broker()
    source_a, source_b = tmp_path / "source-a.py", tmp_path / "source-b.py"
    dest_a, dest_b = tmp_path / "dest-a", tmp_path / "dest-b"
    source_a.write_text("print('new-a')\n")
    source_b.write_text("print('new-b')\n")
    dest_a.write_text("print('old-a')\n")
    dest_b.write_text("print('old-b')\n")
    broker.STATE_DIR = tmp_path / "state"
    broker.DEPLOY_LOCK = broker.STATE_DIR / "lock"
    broker.DEPLOY_BACKUPS = broker.STATE_DIR / "backups"
    broker.DEPLOY_AUDIT = broker.STATE_DIR / "audit"
    broker.DEPLOY_FILES = (("governor/autonomous_agent.py", dest_a), ("governor/engineer_backend.py", dest_b))
    item = approval()
    item["source_hashes"] = {
        "governor/autonomous_agent.py": broker.sha256(source_a),
        "governor/engineer_backend.py": broker.sha256(source_b),
    }
    replies = []
    with mock.patch.object(broker, "load_deploy_approval", return_value=(item, tmp_path / "approval.json")), \
         mock.patch.object(broker, "verify_deploy_source", return_value=[("governor/autonomous_agent.py", source_a), ("governor/engineer_backend.py", source_b)]), \
         mock.patch.object(broker, "require_safe_regular"), mock.patch.object(broker, "require_safe_directory"), \
         mock.patch.object(broker.os, "chown"), \
         mock.patch.object(broker, "restart_and_health", side_effect=health_results), \
         mock.patch.object(broker, "reply", side_effect=replies.append):
        try:
            broker.deploy_engineer_runtime({"operation": "deploy-engineer-runtime", "job_id": "job-1", "target": "pi5"}, "pi5")
        except SystemExit:
            pass
    audit = json.loads((broker.DEPLOY_AUDIT / "job-1.json").read_text())
    return dest_a.read_text(), dest_b.read_text(), audit, replies


def test_success_path_installs_only_two_fixed_files_and_audits(tmp_path):
    a, b, audit, replies = run_transaction(tmp_path, [(True, "healthy")])
    assert (a, b) == ("print('new-a')\n", "print('new-b')\n")
    assert audit["deployment_result"] == "PASS"
    assert audit["rollback_result"] == "not-required"
    assert replies[-1]["status"] == "PASS"


def test_health_failure_restores_both_files_and_audits_rollback(tmp_path):
    a, b, audit, replies = run_transaction(tmp_path, [(False, "health failed"), (True, "healthy")])
    assert (a, b) == ("print('old-a')\n", "print('old-b')\n")
    assert audit["deployment_result"] == "FAIL"
    assert audit["rollback_result"] == "PASS"
    assert replies[-1]["status"] == "FAIL"
