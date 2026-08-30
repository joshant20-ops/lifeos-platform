import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("governor", HERE / "governor.py")
governor_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = governor_module
SPEC.loader.exec_module(governor_module)


class GovernorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gov = governor_module.Governor(HERE / "providers.json", Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_deterministic_always_wins(self):
        job = governor_module.Job("j1", "tests", deterministic_available=True)
        self.assertEqual(self.gov.route(job)["provider"], "deterministic")

    def test_missing_credentials_are_not_retried_as_failures(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            statuses = {x["provider"]: x["status"] for x in self.gov.health()}
            self.assertEqual(statuses["gemini"], "CREDENTIAL_REQUIRED")
            decision = self.gov.route(governor_module.Job("j2", "normal"))
            self.assertEqual(decision["status"], "NO_FREE_PROVIDER_AVAILABLE")
            self.assertFalse(decision["retry"])

    def test_normal_prefers_first_configured_free_cloud(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "test"}, clear=True):
            result = self.gov.route(governor_module.Job("j3", "change"))
            self.assertEqual(result["provider"], "groq")
            self.assertTrue(result["free_only"])

    def test_review_excludes_drafting_provider(self):
        env = {"GROQ_API_KEY": "test", "GEMINI_API_KEY": "test"}
        with mock.patch.dict(os.environ, env, clear=True):
            job = governor_module.Job("j-review", "review", exclude_provider="groq")
            result = self.gov.route(job)
            self.assertEqual(result["provider"], "gemini")

    def test_quota_cooldown_moves_to_next_free_provider(self):
        env = {"GEMINI_API_KEY": "test", "GROQ_API_KEY": "test"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.gov.record("gemini", "QUOTA_429", "j4")
            result = self.gov.route(governor_module.Job("j4", "change"))
            self.assertEqual(result["provider"], "groq")

    def test_retry_cap_stops_routing_to_repeatedly_failing_provider(self):
        env = {"GROQ_API_KEY": "test", "GEMINI_API_KEY": "test"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.gov.record("groq", "FAILURE", "j-cap-1")
            self.gov.record("groq", "FAILURE", "j-cap-2")
            result = self.gov.route(governor_module.Job("j-cap", "change"))
            self.assertEqual(result["provider"], "gemini")
            self.assertEqual(result["attempted"][0]["status"], "RETRY_CAP_REACHED")

    def test_high_risk_is_senior_gated(self):
        result = self.gov.route(governor_module.Job("j5", "production", risk="HIGH_RISK"))
        self.assertEqual(result["provider"], "codex")
        self.assertTrue(result["human_gate"])

    def test_context_excludes_secret_names_and_honours_cap(self):
        root = Path(self.temp.name)
        safe = root / "safe.txt"; safe.write_text("abcdef", encoding="utf-8")
        secret = root / ".env"; secret.write_text("SECRET=x", encoding="utf-8")
        packet = governor_module.compact_packet([secret, safe], 3)
        self.assertEqual([Path(x["path"]).name for x in packet["files"]], ["safe.txt"])
        self.assertEqual(packet["bytes"], 3)
        self.assertTrue(packet["truncated"])


if __name__ == "__main__":
    unittest.main()
