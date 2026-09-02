from pathlib import Path


ROOT = Path(__file__).parents[1]
MODEL = ROOT / "architecture/REPOSITORY_MODEL.md"
DECISION = ROOT / "architecture/decisions/three-repository-authority.md"


def test_normative_repository_model_matches_accepted_three_repo_decision():
    model = MODEL.read_text()
    decision = DECISION.read_text()

    assert "LifeOS uses three repositories" in model
    assert "Status: accepted" in decision
    assert "three-repository-authority.md" in model
    for repository in ("lifeos-platform", "lifeos-jobs", "lifeos-snapshots"):
        assert repository in model
        assert repository in decision


def test_public_entry_points_do_not_prescribe_superseded_two_repo_model():
    entry_points = (
        ROOT / "README.md",
        ROOT / "docs/roadmap.md",
        ROOT / "docs/migration_strategy.md",
        MODEL,
    )
    superseded_phrases = ("two-repository model", "two-repository path")

    for path in entry_points:
        text = path.read_text().lower()
        assert all(phrase not in text for phrase in superseded_phrases), path


def test_repository_model_keeps_raw_and_private_evidence_out_of_git():
    model = MODEL.read_text().lower()

    for prohibition in (
        "raw runtime output stay local",
        "credentials",
        "private documents",
        "personal data",
        "home assistant history",
        "arbitrary logs",
    ):
        assert prohibition in model


def test_superseded_issue_and_relay_gate_have_an_explicit_disposition():
    decision = DECISION.read_text()
    prose = " ".join(decision.split())

    assert "joshant20-ops/lifeos-platform#2" in decision
    assert "0019-two-repo-migration-gate" in decision
    assert "must not be used as acceptance gates" in prose
    assert "Preserve any existing job and result records" in prose
    assert "record the issue as superseded" in prose
