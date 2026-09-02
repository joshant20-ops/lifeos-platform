import importlib.util
import json
import pathlib
from datetime import datetime, timezone
from unittest import mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "homelab/live/usr/local/lib/lifeos_transaction.py"
spec = importlib.util.spec_from_file_location("lifeos_transaction_test", MODULE)
tx = importlib.util.module_from_spec(spec); spec.loader.exec_module(tx)


class Result:
    def __init__(self, returncode=0): self.returncode = returncode; self.stdout = ""; self.stderr = ""


@pytest.fixture
def world(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination_root = tmp_path / "managed"
    destination_root.mkdir()
    destination = destination_root / "example"
    source.write_text("new\n"); destination.write_text("old\n")
    calls = []
    def run(command, timeout=30):
        calls.append(command); return Result()
    monkeypatch.setattr(tx, "ALLOWED_DESTINATIONS", (destination_root,))
    monkeypatch.setattr(tx, "PROTECTED", {destination_root / "protected"})
    monkeypatch.setattr(tx.os, "chown", lambda *args: None)
    controller = tx.Controller(tmp_path / "state", run=run, now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    proposal = {"operation": "replace_file", "risk": "LOW", "component": "acceptance-canary",
                "source": str(source), "destination": str(destination), "sha256": tx.sha256(source),
                "checks": [{"type": "file_sha256", "path": str(destination), "expected": tx.sha256(source)}]}
    return controller, proposal, source, destination, calls


def test_mutation_requires_recovery_point_and_armed_watchdog(world):
    controller, proposal, _, destination, calls = world
    with pytest.raises(tx.TransactionError, match="unavailable"):
        controller.apply("t1")
    manifest = controller.begin("t1", proposal)
    assert manifest["state"] == "ARMED"
    assert (controller.root / "t1/backups/target").read_text() == "old\n"
    assert calls[0] == ["systemctl", "enable", "--now", "lifeos-rollback@t1.timer"]
    controller.apply("t1")
    assert destination.read_text() == "new\n"


def test_failed_watchdog_arm_prevents_mutation_and_cleans_lock(world):
    controller, proposal, _, destination, _ = world
    controller.run = lambda command, timeout=30: Result(1)
    with pytest.raises(tx.TransactionError, match="systemctl"):
        controller.begin("t1", proposal)
    assert destination.read_text() == "old\n"
    assert not (controller.root / "t1").exists()
    assert not list((controller.root / "resource-locks").iterdir())


def test_protected_controller_derived_evidence_commits_and_disarms(world):
    controller, proposal, _, _, calls = world
    controller.begin("t1", proposal); controller.apply("t1")
    proof = controller.verify("t1")
    assert proof["derived_by"] == "protected-controller"
    committed = controller.commit("t1")
    assert committed["state"] == "COMMITTED"
    assert calls[-1] == ["systemctl", "disable", "--now", "lifeos-rollback@t1.timer"]


def test_model_assertion_cannot_commit(world):
    controller, proposal, _, _, _ = world
    controller.begin("t1", proposal); controller.apply("t1")
    manifest = controller.status("t1"); manifest["state"] = "PROBATION"; controller._save(manifest)
    (controller.root / "t1/verification.json").write_text(json.dumps({"accepted": True, "derived_by": "model", "evidence": []}))
    with pytest.raises(tx.TransactionError, match="evidence rejected"):
        controller.commit("t1")


def test_critical_failure_rolls_back_immediately(world):
    controller, proposal, _, destination, _ = world
    proposal["checks"].append({"type": "service_active", "unit": "broken.service"})
    controller.run = lambda command, timeout=30: Result(1 if "is-active" in command else 0)
    controller.begin("t1", proposal); controller.apply("t1")
    with pytest.raises(tx.TransactionError, match="critical verification"):
        controller.verify("t1")
    assert destination.read_text() == "old\n"
    assert controller.status("t1")["state"] == "ROLLED_BACK"


def test_watchdog_rollback_restores_file_without_governor(world):
    controller, proposal, _, destination, _ = world
    controller.begin("t1", proposal); controller.apply("t1")
    # This is the only operation performed by the independent systemd service.
    result = controller.rollback("t1", "health deadline expired")
    assert destination.read_text() == "old\n"
    assert result["rollback"] == {"result": "PASS", "reason": "health deadline expired", "at": "2026-01-01T00:00:00+00:00", "watchdog_disarmed": True}


def test_conflicting_transactions_are_rejected_and_state_is_durable(world):
    controller, proposal, _, _, _ = world
    controller.begin("t1", proposal)
    with pytest.raises(tx.TransactionError, match="conflicting"):
        controller.begin("t2", proposal)
    restarted = tx.Controller(controller.root, run=controller.run, now=controller.now)
    assert restarted.status("t1")["state"] == "ARMED"


@pytest.mark.parametrize("operation", ["shell", "package_install", "replace-file"])
def test_unknown_operations_fail_closed(world, operation):
    controller, proposal, _, _, _ = world
    proposal["operation"] = operation
    with pytest.raises(tx.TransactionError, match="not allowlisted"):
        controller.begin("t1", proposal)


def test_protected_recovery_core_cannot_be_replaced(world):
    controller, proposal, _, _, _ = world
    proposal["destination"] = str(next(iter(tx.PROTECTED)))
    with pytest.raises(tx.TransactionError, match="not allowlisted"):
        controller.begin("t1", proposal)


def test_unrelated_good_check_cannot_authorize_changed_artifact(world):
    controller, proposal, _, destination, _ = world
    proposal["checks"] = [{"type": "service_active", "unit": "lifeos-governor.service"}]
    with pytest.raises(tx.TransactionError, match="destination hash"):
        controller.begin("t1", proposal)


def test_timer_is_persistent_two_hour_independent_unit():
    timer = (ROOT / "governor/systemd/lifeos-rollback@.timer").read_text()
    service = (ROOT / "governor/systemd/lifeos-rollback@.service").read_text()
    assert "OnActiveSec=2h" in timer and "Persistent=true" in timer
    assert "ExecStart=/usr/local/sbin/lifeos-rollback %i" in service
    assert "Governor" not in service
