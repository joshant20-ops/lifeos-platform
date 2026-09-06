from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "governor/scripts/lifeos-cloud-builder").read_text()


def test_cloud_builder_scaffold_avoids_known_privacy_classifier_literals():
    # The cloud-builder wrapper is only invoked after the Governor has already
    # classified the job as cloud-safe. Its own safety boilerplate must not
    # re-trigger the broker's content classifier inside OpenHands.
    scaffold = SCRIPT.split("USER GOAL:", 1)[0].lower()
    assert "paperless" not in scaffold
    assert "private documents" not in scaffold
    assert "private records" not in scaffold
    assert "private data" not in scaffold
    assert "personal documents" not in scaffold
    assert "bank statements" not in scaffold
    assert "financial records" not in scaffold


def test_cloud_builder_still_states_privacy_boundary_without_trigger_terms():
    assert "protected runtime jobs" in SCRIPT
    assert "Governor privacy policy is authoritative" in SCRIPT
