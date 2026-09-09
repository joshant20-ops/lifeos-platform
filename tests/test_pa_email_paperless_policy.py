import importlib.util
import unittest
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


class SelectivePolicyTests(unittest.TestCase):
    def test_authorizes_only_selected_synthetic_pdf(self):
        module = load()
        result = module.policy(
            {"disposition": "archive authoritative attachment"},
            attachment(),
        )
        self.assertEqual(result, {
            "disposition": "archive authoritative attachment",
            "authorized": True,
            "allowed": True,
        })

    def test_rejects_nonarchive_decision(self):
        module = load()
        result = module.policy({"disposition": "event/action only"}, attachment())
        self.assertTrue(result["allowed"])
        self.assertFalse(result["authorized"])

    def test_rejects_untrusted_attachment(self):
        module = load()
        self.assertFalse(module.policy(
            {"disposition": "archive authoritative attachment"},
            attachment(filename="private.pdf"),
        )["authorized"])
        self.assertFalse(module.policy(
            {"disposition": "archive authoritative attachment"},
            attachment(mime="application/octet-stream"),
        )["authorized"])


if __name__ == "__main__":
    unittest.main()
