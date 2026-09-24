from pathlib import Path


def test_governor_delegates_engineering_iteration_to_ots_agent():
    source = Path("governor/autonomous_agent.py").read_text()
    start = source.index("def _execute_job_locked(job):")
    end = source.index("def execute_job(job):", start)
    execute = source[start:end]
    assert 'job["engineering_loop"] = "ots-owned"' in execute
    assert "run_builder(" in execute
    assert "independent_verify(" in execute
    assert 'set_stage(job, "publication"' in execute
    assert 'set_stage(job, "runtime"' in execute
    assert "spawn_continuation" not in source


def test_boundary_document_preserves_control_plane_invariants():
    doc = Path("docs/governor-ots-boundary.md").read_text()
    for required in (
        "privacy classification",
        "Tower lease",
        "bounded patch publication",
        "independent local acceptance",
        "local-only work -> local builder/Tower route",
        "no direct sudo assumption",
    ):
        assert required in doc
