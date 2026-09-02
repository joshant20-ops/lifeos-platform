from pathlib import Path


LAUNCHER = Path(__file__).parents[1] / "governor/runtime_jobs/bce3a28c459c.sh"


def test_launcher_is_safe_bounded_and_fail_closed():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail")
    assert 'timeout --signal=TERM --kill-after=10s' in text
    assert 'merge --ff-only "$remote_head"' in text
    assert "reset --hard" not in text
    assert "DISCOVERED_ISSUES_JSON_B64=none" in text
    assert "RESULT=$5" in text


def test_manifest_parser_supports_queued_split_repository_contract():
    text = LAUNCHER.read_text()
    assert 'repo = value(data, repo_keys)' in text
    assert 'commit = value(source,' in text
    assert 'path = value(source,' in text
    assert 'digest = value(source,' in text
    assert 'if len(sources) != 1:' in text


def test_launcher_pins_migration_identity_and_waits_for_relay_pass():
    text = LAUNCHER.read_text()
    assert "3a93d6e9e99fe04f62f8a452b688639cefb05b82" in text
    assert "d9a4d225cd16663ec1ed5f0f909b615e4c1f9b91" in text
    assert 'result.get("classification") == "PASS"' in text
    assert "PI_RELAY_RESULT=PASS" in text
