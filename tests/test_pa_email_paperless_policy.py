import importlib.util
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "homelab/live/home/joshan/automation/lifeos_email_paperless_selective.py"
)


def load():
    spec = importlib.util.spec_from_file_location("selective_route", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def attachment(**overrides):
    value = {
        "filename": "lifeos-synthetic-proof.pdf",
        "mime": "application/pdf",
        "payload": b"%PDF synthetic",
    }
    value.update(overrides)
    return value


def test_policy_authorizes_only_selected_synthetic_pdf():
    module = load()
    result = module.policy(
        {"disposition": "archive authoritative attachment"},
        attachment(),
    )
    assert result == {
        "disposition": "archive authoritative attachment",
        "authorized": True,
        "allowed": True,
    }


def test_policy_rejects_nonarchive_decision():
    module = load()
    result = module.policy({"disposition": "event/action only"}, attachment())
    assert result["allowed"] is True
    assert result["authorized"] is False


def test_policy_rejects_untrusted_attachment():
    module = load()
    assert not module.policy(
        {"disposition": "archive authoritative attachment"},
        attachment(filename="private.pdf"),
    )["authorized"]
    assert not module.policy(
        {"disposition": "archive authoritative attachment"},
        attachment(mime="application/octet-stream"),
    )["authorized"]
