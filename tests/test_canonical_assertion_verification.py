import importlib.machinery
import os
import pathlib
import subprocess


SOURCE = pathlib.Path("governor/autonomous_agent.py")


def load_agent(tmp_path):
    previous = os.environ.get("LIFEOS_AGENT_STATE")
    os.environ["LIFEOS_AGENT_STATE"] = str(tmp_path / "state")
    try:
        return importlib.machinery.SourceFileLoader(
            f"canonical_assertion_agent_{tmp_path.name}", str(SOURCE)
        ).load_module()
    finally:
        if previous is None:
            os.environ.pop("LIFEOS_AGENT_STATE", None)
        else:
            os.environ["LIFEOS_AGENT_STATE"] = previous


def canonical_repo(tmp_path, text):
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", remote],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "clone", remote, repo], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "Test"], check=True)
    (repo / "fixture.txt").write_text(text)
    subprocess.run(["git", "-C", repo, "add", "fixture.txt"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-m", "fixture"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "push", "-u", "origin", "main"], check=True, capture_output=True)
    return repo


def assertion_job(module):
    return module.new_job(
        "Verify a harmless canonical outcome.",
        canonical_assertions=[{
            "id": "acceptance-marker",
            "kind": "tracked_text_contains",
            "value": "GENERIC_ACCEPTANCE=PASS",
        }],
    )


def test_no_change_handoff_passes_when_canonical_assertion_is_satisfied(tmp_path):
    module = load_agent(tmp_path)
    module.PLATFORM_REPO = canonical_repo(tmp_path, "GENERIC_ACCEPTANCE=PASS\n")
    # Verification is a local acceptance boundary. Mission Control/publication
    # already synchronize origin/main, so it must not require network access.
    (tmp_path / "remote.git").rename(tmp_path / "remote-offline.git")
    job = assertion_job(module)

    result, evidence = module.verify_canonical_assertions(job)
    verdict = module.independent_verify(job, 1, "PI5_PATCH=none\n", result)

    assert result is True
    assert "CANONICAL_ASSERTION_ACCEPTANCE_MARKER=PASS" in evidence
    assert verdict["verdict"] == "PASS"


def test_no_change_handoff_retries_when_canonical_assertion_is_unsatisfied(tmp_path):
    module = load_agent(tmp_path)
    module.PLATFORM_REPO = canonical_repo(tmp_path, "GENERIC_ACCEPTANCE=PENDING\n")
    job = assertion_job(module)

    result, evidence = module.verify_canonical_assertions(job)
    verdict = module.independent_verify(job, 1, "PI5_PATCH=none\n", result)

    assert result is False
    assert "CANONICAL_ASSERTION_ACCEPTANCE_MARKER=FAIL" in evidence
    assert verdict["verdict"] == "RETRY"


def test_canonical_assertion_contract_rejects_executable_or_unbounded_input(tmp_path):
    module = load_agent(tmp_path)
    for assertion in (
        {"id": "bad", "kind": "shell", "value": "true"},
        {"id": "bad", "kind": "tracked_text_contains", "value": "x\ny"},
    ):
        try:
            module.new_job("test", canonical_assertions=[assertion])
            assert False, assertion
        except ValueError:
            pass


def test_tracked_path_absent_assertion_passes_only_when_path_is_missing(tmp_path):
    module = load_agent(tmp_path)
    repo = canonical_repo(tmp_path, "fixture\n")
    module.PLATFORM_REPO = repo
    missing_job = module.new_job(
        "Verify stale trigger is absent.",
        canonical_assertions=[{
            "id": "stale-trigger-absent",
            "kind": "tracked_path_absent",
            "value": "deploy-triggers/issue-old",
        }],
    )

    result, evidence = module.verify_canonical_assertions(missing_job)
    assert result is True
    assert "CANONICAL_ASSERTION_STALE_TRIGGER_ABSENT=PASS" in evidence

    (repo / "deploy-triggers").mkdir()
    (repo / "deploy-triggers" / "issue-old").write_text("trigger\n")
    subprocess.run(["git", "-C", repo, "add", "deploy-triggers/issue-old"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-m", "add stale trigger"], check=True, capture_output=True)
    subprocess.run(["git", "-C", repo, "push", "origin", "main"], check=True, capture_output=True)

    result, evidence = module.verify_canonical_assertions(missing_job)
    assert result is False
    assert "CANONICAL_ASSERTION_STALE_TRIGGER_ABSENT=FAIL" in evidence
