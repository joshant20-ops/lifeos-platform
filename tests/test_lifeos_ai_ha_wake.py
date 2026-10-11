import importlib.util
import pathlib

HELPER_PATH = pathlib.Path(__file__).resolve().parents[1] / "governor" / "scripts" / "lifeos-ai-ha-wake.py"
HELPER_SPEC = importlib.util.spec_from_file_location("lifeos_ai_ha_wake", HELPER_PATH)
HA_HELPER = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(HA_HELPER)


def test_fixed_ha_helper_checks_lifeos_entities_without_waking(monkeypatch):
    calls = []
    monkeypatch.setattr(HA_HELPER.os, "geteuid", lambda: 0)
    monkeypatch.setattr(HA_HELPER.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))

    assert HA_HELPER.main(["--check"]) == 0

    args, kwargs = calls[0]
    assert args[:4] == [
        "/usr/local/sbin/lifeos-secret",
        "exec",
        "homeassistant.long_lived_access_token",
        "HA_TOKEN",
    ]
    script = args[-1]
    assert "api/states/switch.z97_power" in script
    assert "predbat.status" not in script
    assert "sensor.lifeos_grid_import_power" not in script
    assert "switch.turn_on" not in script
    assert kwargs["check"] is True


def test_fixed_ha_helper_calls_only_the_proven_tower_switch(monkeypatch):
    calls = []
    monkeypatch.setattr(HA_HELPER.os, "geteuid", lambda: 0)
    monkeypatch.setattr(HA_HELPER.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))

    assert HA_HELPER.main([]) == 0

    args, kwargs = calls[0]
    script = args[-1]
    assert "http://127.0.0.1:8123/api/services/switch/turn_on" in script
    assert '"switch.z97_power"' in script
    assert kwargs["check"] is True


def test_fixed_ha_helper_rejects_arbitrary_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(HA_HELPER.os, "geteuid", lambda: 0)
    monkeypatch.setattr(HA_HELPER.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    assert HA_HELPER.main(["--check", "anything"]) == 64
    assert calls == []


def test_sudoers_grant_is_limited_to_fixed_helper_modes():
    sudoers_path = HELPER_PATH.with_suffix(".sudoers")
    assert sudoers_path.read_text().strip() == (
        'joshan ALL=(root) NOPASSWD: /usr/local/sbin/lifeos-ai-ha-wake "", '
        + "/usr/local/sbin/lifeos-ai-ha-wake --check"
    )
