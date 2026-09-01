import importlib.machinery
import importlib.util
import json
import pathlib
from unittest import mock

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "governor/target_identity.py"
AGENT = ROOT / "governor/autonomous_agent.py"
BROKER = ROOT / "homelab/live/usr/local/sbin/lifeos-root-broker"
HISTORICAL = ROOT / "governor/runtime_jobs/af179d3cf1f7.sh"
LAUNCHER = ROOT / "governor/runtime_jobs/83d0e4005cef.sh"
HISTORICAL_SHA256 = "37707030baed18a8717a79ec6fcc116f8be893e6a1ae6b3fac76b50f971efb0d"


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("target_id", ["pi5-docker", "rack-controller-42", "target.with_symbols"])
def test_authoritative_target_id_is_read(tmp_path, target_id):
    identity = load(IDENTITY, "target_identity_" + target_id.replace("-", "_"))
    path = tmp_path / "identity.json"
    path.write_text(json.dumps({"target_id": target_id}))
    assert identity.load_target_id(path) == target_id


@pytest.mark.parametrize("contents", [None, "{bad json", "{}", '{"target_id":""}'])
def test_identity_errors_fail_closed(tmp_path, contents):
    identity = load(IDENTITY, "target_identity_failure")
    path = tmp_path / "identity.json"
    if contents is not None:
        path.write_text(contents)
    with pytest.raises(identity.TargetIdentityError):
        identity.load_target_id(path)


@pytest.mark.parametrize(
    "operation", ["deploy-engineer-runtime", "deploy-autonomous-agent", "deploy-backlog-runner"]
)
def test_governor_deployment_requests_use_authoritative_target(tmp_path, monkeypatch, operation):
    monkeypatch.setenv("LIFEOS_AGENT_STATE", str(tmp_path))
    agent = load(AGENT, "targeted_agent_" + operation)
    sent = bytearray()

    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, _timeout): pass
        def connect(self, _path): pass
        def sendall(self, payload): sent.extend(payload)
        def shutdown(self, _how): pass
        def recv(self, _size): return b'{"status":"PASS"}' if not hasattr(self, "read") else b""

    def recv_once(self, _size):
        if getattr(self, "read", False): return b""
        self.read = True
        return b'{"status":"PASS"}'

    FakeSocket.recv = recv_once
    with mock.patch.object(agent, "load_target_id", return_value="arbitrary-controller"), \
         mock.patch.object(agent.socket, "socket", return_value=FakeSocket()):
        assert agent.request_bounded_deployment("job-1", operation)["status"] == "PASS"
    assert json.loads(sent)["target"] == "arbitrary-controller"


def test_active_governor_deployment_client_does_not_embed_legacy_target():
    source = AGENT.read_text()
    deployment_client = source[source.index("def request_bounded_deployment"):source.index("PRIVATE_PATTERNS")]
    assert '"pi5"' not in deployment_client
    assert "load_target_id()" in deployment_client


def test_broker_still_rejects_mismatched_target():
    broker = load(BROKER, "target_equality_broker")
    with mock.patch.object(broker, "reply") as reply, pytest.raises(SystemExit):
        broker.validate_common({"job_id": "job-1", "target": "pi5"}, "pi5-docker")
    assert reply.call_args.args[0]["reason"] == "target identity mismatch"


def test_failed_historical_bootstrap_is_unchanged():
    import hashlib
    assert hashlib.sha256(HISTORICAL.read_bytes()).hexdigest() == HISTORICAL_SHA256


def test_replacement_launcher_is_safe_publication_gated_and_not_legacy_targeted():
    source = LAUNCHER.read_text()
    assert LAUNCHER.is_file() and not LAUNCHER.is_symlink()
    assert LAUNCHER.stat().st_mode & 0o111
    assert source.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail\n")
    for required in (
        "/etc/lifeos-control/identity.json",
        "refs/remotes/origin/main",
        "git -C \"$REPO\" ls-files --error-unmatch",
        "deploy-autonomous-agent",
        "deploy-backlog-runner",
        "http://127.0.0.1:8790/health",
        "systemctl stop lifeos-backlog-runner.timer",
        "ROLLBACK_REQUIRED=1",
        "NEW_BOOTSTRAP_SHA256=",
    ):
        assert required in source
    assert '"target": "pi5"' not in source
