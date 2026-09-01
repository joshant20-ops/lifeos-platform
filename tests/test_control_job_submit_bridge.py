import hashlib
import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import threading
from unittest import mock

import pytest

SOURCE = pathlib.Path("homelab/live/usr/local/libexec/lifeos-control-job-submit-bridge")
PUBLISHER = pathlib.Path("homelab/live/usr/local/sbin/lifeos-job-publisher")


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def bridge(tmp_path):
    m = load(SOURCE, "submit_bridge")
    m.REPO = tmp_path
    m.LOCK = tmp_path / "run/submit.lock"
    for rel in (*m.ROOTS.values(), "jobs/staging", "jobs/pending", "jobs/archive", "results"):
        (tmp_path / rel).mkdir(parents=True)
    return m


def package(scope="root-broker", job_id="approved-001", script=b"#!/usr/bin/env bash\nexit 0\n"):
    root = {"diagnostic": "jobs/scripts", "control-state": "jobs/change-scripts", "root-broker": "jobs/root-scripts"}[scope]
    d = {"schema_version": 1, "job_id": job_id, "target": "pi5", "job_type": "diagnostic" if scope == "diagnostic" else "change",
         "script": f"{root}/{job_id}.sh", "script_sha256": hashlib.sha256(script).hexdigest(),
         "timeout_seconds": 30, "created_by": "lifeos-engineer", "description": "already approved test package"}
    if scope != "diagnostic":
        d.update(change_scope=scope, change_policy="gated-v1", requires_root=scope == "root-broker")
    return d, script


def send(m, d, script):
    return m.submit(json.dumps(d).encode(), script, 1234)


def test_accepts_only_canonical_root_and_staging(bridge):
    d, script = package()
    send(bridge, d, script)
    assert (bridge.REPO / d["script"]).read_bytes() == script
    assert json.loads((bridge.REPO / "jobs/staging/approved-001.json").read_text()) == d
    assert not list((bridge.REPO / "jobs/pending").iterdir())
    assert not list((bridge.REPO / "results").iterdir())


@pytest.mark.parametrize("mutation,reason", [
    (lambda d: d.update(script="jobs/root-scripts/../escape.sh"), "canonical"),
    (lambda d: d.update(script="/tmp/escape.sh"), "canonical"),
    (lambda d: d.update(change_scope="other"), "scope"),
    (lambda d: d.update(requires_root=False), "requires_root"),
    (lambda d: d.update(destination="/tmp/pwn"), "unexpected"),
    (lambda d: d.update(command="id", args=["-u"]), "unexpected"),
])
def test_adversarial_manifest_rejected(bridge, mutation, reason):
    d, script = package(); mutation(d)
    with pytest.raises(bridge.Rejected, match=reason): send(bridge, d, script)
    assert not list((bridge.REPO / "jobs/staging").iterdir())


def test_malformed_json_checksum_oversize_and_symlink_escape(bridge, tmp_path):
    with pytest.raises(bridge.Rejected, match="malformed"):
        bridge.submit(b"{", b"x", 1)
    d, script = package(); d["script_sha256"] = "0" * 64
    with pytest.raises(bridge.Rejected, match="checksum"):
        send(bridge, d, script)
    d, script = package(job_id="large")
    with pytest.raises(bridge.Rejected, match="size"):
        send(bridge, d, b"x" * (bridge.MAX_SCRIPT + 1))
    root = bridge.REPO / "jobs/root-scripts"
    root.rmdir(); root.symlink_to(tmp_path / "outside", target_is_directory=True)
    (tmp_path / "outside").mkdir()
    d, script = package(job_id="symlink")
    with pytest.raises(bridge.Rejected, match="unsafe"):
        send(bridge, d, script)


@pytest.mark.parametrize("conflict", ["jobs/staging", "jobs/pending", "jobs/archive", "results"])
def test_duplicate_and_replay_conflicts(bridge, conflict):
    d, script = package()
    suffix = ".json"
    (bridge.REPO / conflict / (d["job_id"] + suffix)).write_text("evidence")
    with pytest.raises(bridge.Rejected, match="duplicate/replay"):
        send(bridge, d, script)


def test_concurrent_submit_has_exactly_one_winner(bridge):
    d, script = package(); outcomes = []
    def run():
        try: send(bridge, d, script); outcomes.append("accepted")
        except bridge.Rejected: outcomes.append("rejected")
    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(outcomes) == ["accepted", "rejected"]


def test_publisher_promotes_bridge_job_in_existing_fifo_order(bridge):
    publisher = load(PUBLISHER, "publisher_for_bridge")
    publisher.REPO = bridge.REPO
    publisher.STAGING = bridge.REPO / "jobs/staging"; publisher.PENDING = bridge.REPO / "jobs/pending"
    publisher.ARCHIVE = bridge.REPO / "jobs/archive"; publisher.RESULTS = bridge.REPO / "results"
    publisher.STATE_DIR = bridge.REPO / "state"
    publisher.SCRIPT_ROOTS = {k: bridge.REPO / v for k, v in bridge.ROOTS.items()}
    older, old_script = package("diagnostic", "0001-older")
    newer, new_script = package("root-broker", "0002-engineer")
    send(bridge, older, old_script); send(bridge, newer, new_script)
    promoted = []
    def promote(manifest, data, script):
        promoted.append(data["job_id"]); manifest.rename(publisher.PENDING / manifest.name)
    with mock.patch.object(publisher, "sync_repo"), mock.patch.object(publisher, "gitleaks", return_value=True), mock.patch.object(publisher, "promote_one", side_effect=promote):
        assert publisher.main() == 0
    assert promoted == ["0001-older"]
    assert (publisher.STAGING / "0002-engineer.json").exists()


def test_engineer_client_surface_has_no_destination_or_command():
    text = pathlib.Path("governor/autonomous_agent.py").read_text()
    start = text.index("def submit_control_job")
    end = text.index("\ndef request_engineer_runtime_deployment", start)
    function = text[start:end]
    assert '"operation": "submit-control-job"' in function
    assert '"manifest": manifest_json' in function and '"script_base64"' in function
    assert "destination" not in function and '"command"' not in function and '"args"' not in function


def test_job_specific_activation_launcher_is_bounded_and_human_gated():
    path = pathlib.Path("governor/runtime_jobs/cb5fdbe62b15.sh")
    text = path.read_text()
    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "HUMAN_ACTION_REQUIRED=" in text
    assert "timeout --signal=TERM --kill-after=30s 2100s" in text
    assert "governor/runtime_jobs/d2dd520ff95b.sh" in text
    assert "RESULT=BLOCKED" in text
