import base64
import importlib.machinery
import os
import pathlib
import subprocess

import pytest


SOURCE = pathlib.Path("governor/autonomous_agent.py")
REAL_SUBPROCESS_RUN = subprocess.run


def load_agent(name, state):
    previous = os.environ.get("LIFEOS_AGENT_STATE")
    os.environ["LIFEOS_AGENT_STATE"] = str(state)
    try:
        return importlib.machinery.SourceFileLoader(name, str(SOURCE)).load_module()
    finally:
        if previous is None:
            os.environ.pop("LIFEOS_AGENT_STATE", None)
        else:
            os.environ["LIFEOS_AGENT_STATE"] = previous


def command(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


@pytest.fixture
def agent_repo(tmp_path):
    repo = tmp_path / "platform"
    origin = tmp_path / "origin.git"
    state = tmp_path / "state"
    module = load_agent(f"artifact_agent_{tmp_path.name}", state)
    # Some legacy publisher tests replace the shared subprocess module directly.
    module.subprocess.run = REAL_SUBPROCESS_RUN
    repo.mkdir()
    command("git", "init", "--initial-branch=main", cwd=repo)
    command("git", "config", "user.name", "Test", cwd=repo)
    command("git", "config", "user.email", "test@localhost", cwd=repo)
    (repo / "README").write_text("fixture\n")
    command("git", "add", "README", cwd=repo)
    command("git", "commit", "-m", "fixture", cwd=repo)
    command("git", "init", "--bare", str(origin))
    command("git", "remote", "add", "origin", str(origin), cwd=repo)
    command("git", "push", "-u", "origin", "main", cwd=repo)
    module.PLATFORM_REPO = repo.resolve()
    module.ROOT = state
    return module, repo, origin, state


def handoff(job_id, text="#!/usr/bin/env bash\necho PASS\n", route="normal"):
    return {
        "run_script": f"governor/runtime_jobs/{job_id}.sh",
        "runtime_b64": base64.b64encode(text.encode()).decode(),
        "_builder_route": route,
    }


def test_generated_launcher_is_published_with_exact_origin_blob(agent_repo):
    module, repo, _, _ = agent_repo
    job = {"id": "826cbeaec0c9", "privacy": "normal"}
    ok, evidence = module.publish_runtime_artifact(job, handoff(job["id"]))
    target = repo / "governor/runtime_jobs/826cbeaec0c9.sh"
    assert ok, evidence
    assert target.is_file() and not target.is_symlink() and os.access(target, os.X_OK)
    assert "RUNTIME_ARTIFACT_PUBLISHED=PASS" in evidence
    assert f"RUNTIME_ARTIFACT_SHA256={module.hashlib.sha256(target.read_bytes()).hexdigest()}" in evidence
    commit = command("git", "log", "-1", "--format=%H", "--", str(target.relative_to(repo)), cwd=repo).stdout.strip()
    assert f"RUNTIME_ARTIFACT_COMMIT={commit}" in evidence
    assert command("git", "show", f"origin/main:{target.relative_to(repo)}", cwd=repo).stdout == target.read_text()


def test_dirty_checkout_preserves_candidate_and_emits_no_runnable_path(agent_repo):
    module, repo, _, state = agent_repo
    (repo / "README").write_text("dirty\n")
    job = {"id": "dirty123", "privacy": "normal"}
    ok, evidence = module.publish_runtime_artifact(job, handoff(job["id"]))
    assert not ok
    assert (state / "artifact_candidates/dirty123.sh").is_file()
    assert not (repo / "governor/runtime_jobs/dirty123.sh").exists()
    assert "HUMAN_ACTION_REQUIRED_ARTIFACT_NOT_PUBLISHED" in evidence
    assert "sudo " not in evidence


def test_push_failure_is_truthful_and_candidate_survives(agent_repo):
    module, repo, origin, state = agent_repo
    command("git", "remote", "set-url", "--push", "origin", str(origin / "missing"), cwd=repo)
    job = {"id": "pushfail123", "privacy": "normal"}
    ok, evidence = module.publish_runtime_artifact(job, handoff(job["id"]))
    assert not ok
    assert (state / "artifact_candidates/pushfail123.sh").is_file()
    assert "RUNTIME_ARTIFACT_PUBLISHED=FAIL" in evidence
    assert "HUMAN_ACTION_REQUIRED_ARTIFACT_NOT_PUBLISHED" in evidence


def test_publication_is_idempotent(agent_repo):
    module, _, _, _ = agent_repo
    job = {"id": "retry123", "privacy": "normal"}
    first = module.publish_runtime_artifact(job, handoff(job["id"]))
    second = module.publish_runtime_artifact(job, handoff(job["id"]))
    assert first[0] and second[0], (first, second)
    assert second[1].endswith("RUNTIME_ARTIFACT_PUBLISHED=PASS\n")


def test_path_containment_and_symlink_are_rejected(agent_repo):
    module, repo, _, _ = agent_repo
    job = {"id": "safe123", "privacy": "normal"}
    bad = handoff(job["id"])
    bad["run_script"] = "governor/runtime_jobs/../escape.sh"
    assert not module.publish_runtime_artifact(job, bad)[0]
    target = repo / "governor/runtime_jobs/safe123.sh"
    target.parent.mkdir(parents=True)
    target.symlink_to(repo / "README")
    ok, evidence = module.publish_runtime_artifact(job, handoff(job["id"]))
    assert not ok
    assert "symlink_rejected" in evidence or "canonical_checkout_dirty" in evidence


def test_normal_and_local_builder_routing(agent_repo, tmp_path, monkeypatch):
    module, _, _, _ = agent_repo
    local = tmp_path / "local-builder"
    local.write_text("#!/usr/bin/env bash\nprintf 'local'\n")
    local.chmod(0o755)
    monkeypatch.setattr(module, "BUILDER", "/normal-builder")
    monkeypatch.setattr(module, "LOCAL_BUILDER", str(local))
    assert module.builder_route({"privacy": "normal"}) == ("normal", "/normal-builder")
    assert module.builder_route({"privacy": "local-only"}) == ("local", str(local))


def test_local_only_never_falls_through_to_cloud_and_verifier_contract_remains(agent_repo, monkeypatch):
    module, _, _, _ = agent_repo
    monkeypatch.setattr(module, "LOCAL_BUILDER", "")
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    rc, evidence, result = module.run_builder(
        {"id": "private123", "privacy": "local-only", "request": "private documents"}, 1
    )
    assert rc == 78 and "LOCAL_BUILDER=UNAVAILABLE" in evidence
    assert result["_builder_route"] == "local" and not called
    assert callable(module.local_verify)
