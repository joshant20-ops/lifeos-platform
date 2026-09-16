import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_nonpersonal_cloud_builder_keeps_codex_available_and_private_guard():
    script = (ROOT / "governor/scripts/lifeos-cloud-builder").read_text()
    assert 'cloud_builder_forbidden_for_local_only_job' in script
    assert 'if [[ "$CODEX" == present ]]' in script
    assert 'AGENTS+=("codex|codex|")' in script
    assert 'AGENTS+=("governor-broker|openhands|' not in script


def test_stable_base_policy_has_no_direct_cloud_ai_provider():
    text = (ROOT / "governor/policy.json").read_text()
    assert '"adapter": "direct-cloud"' not in text
