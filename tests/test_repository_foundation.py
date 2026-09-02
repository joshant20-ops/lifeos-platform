from pathlib import Path


ROOT = Path(__file__).parents[1]
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


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def prose(relative: str) -> str:
    return " ".join(read(relative).split())


def test_required_foundation_files_exist_and_are_nonempty():
    for relative in REQUIRED:
        path = ROOT / relative
        assert path.is_file(), relative
        assert not path.is_symlink(), relative
        assert read(relative).strip(), relative


def test_authority_and_execution_contract_is_explicit():
    architecture = prose("docs/architecture_overview.md")
    assert "canonical source of truth" in read("README.md").lower()
    assert "Pi5 is the permanent, always-on Governor and control plane" in architecture
    assert "Watchman is the sole runtime execution gatekeeper" in architecture
    assert "Z97" in architecture and "migration-only" in architecture


def test_worker_boundaries_and_communication_are_consistent():
    architecture = read("docs/architecture_overview.md")
    communication = read("governance/communication.md")
    for worker in ("Engineer", "Auditor", "Personal Assistant"):
        assert worker in architecture
        assert worker in communication
    assert "directly import" in communication
    assert "versioned files" in communication
    assert "explicit queue records" in communication
    assert "repository state" in communication


def test_open_source_and_unresolved_decision_policy_is_documented():
    assert "Prefer maintained open-source components" in read("AGENTS.md")
    for relative in (
        "docs/architecture_overview.md",
        "docs/roadmap.md",
        "docs/migration_strategy.md",
        "bootstrap/README.md",
        "governance/communication.md",
    ):
        assert "TODO" in read(relative), relative


def test_foundation_bootstrap_scope_contains_no_executable_content():
    bootstrap_files = tuple((ROOT / "bootstrap").rglob("*"))
    assert bootstrap_files == (ROOT / "bootstrap/README.md",)
    assert not any((ROOT / relative).name == "Dockerfile" for relative in REQUIRED)


def test_foundation_docs_do_not_contain_host_specific_network_addresses():
    combined = "\n".join(read(relative) for relative in REQUIRED)
    # Architectural role names are expected, but LAN and loopback endpoints are
    # outside the governed foundation's documentation scope.
    forbidden_fragments = ("192.168.", "10.0.", "127.0.0.1", "localhost:")
    for fragment in forbidden_fragments:
        assert fragment not in combined
