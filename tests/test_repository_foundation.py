from pathlib import Path


ROOT = Path(__file__).parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/242407bcc655.sh"
REQUIRED = (
    "README.md",
    "AGENTS.md",
    "docs/architecture_overview.md",
    "docs/roadmap.md",
    "docs/migration_strategy.md",
    ".github/copilot-instructions.md",
    "bootstrap/README.md",
    "governance/communication.md",
)


def test_required_foundation_files_exist_and_are_nonempty():
    for relative in REQUIRED:
        path = ROOT / relative
        assert path.is_file(), relative
        assert path.read_text(encoding="utf-8").strip(), relative


def test_foundation_contract_is_consistent_across_governance_docs():
    combined = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in REQUIRED)
    for statement in (
        "canonical source of truth",
        "Pi5",
        "Watchman",
        "Engineer",
        "Auditor",
        "Personal Assistant",
        "TODO",
    ):
        assert statement in combined
    communication = (ROOT / "governance/communication.md").read_text(encoding="utf-8")
    assert "directly import" in communication
    assert "versioned files" in communication
    assert "explicit queue records" in communication
    assert "repository state" in communication


def test_pi_launcher_is_bounded_and_enforces_review_contract():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "timeout --signal=TERM --kill-after=10s" in text
    assert "review_branch_is_default" in text
    assert "copilot-swe-agent[bot]" in text
    assert "gh pr create" in text
    assert "--draft --title \"$PR_TITLE\"" in text
    assert "git commit" not in text
    assert "docker" not in text.lower()


def test_pi_launcher_emits_iteration_contract():
    text = LAUNCHER.read_text(encoding="utf-8")
    for field in (
        "ISSUE_VALIDITY=",
        "LIFEOS_WORK_STATE=",
        "BARRIER=",
        "NEXT_AUTONOMOUS_ACTION=",
        "DISCOVERED_ISSUES_JSON_B64=",
        "RESULT=",
        "TESTS=",
        "NEXT_RUNTIME_CHECK=",
    ):
        assert field in text
