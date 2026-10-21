"""Privacy and queue checks for local task review."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = ROOT / "homelab" / "live" / "home" / "joshan" / "automation"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AUTOMATION))
SPEC = importlib.util.spec_from_file_location("lifeos_task_review_tests", AUTOMATION / "lifeos_task_reconciler.py")
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


class PATaskReviewTests(unittest.TestCase):
    def test_review_forces_local_provider_and_only_returns_analysis_fields(self):
        evidence = {"task": {"title": "Synthetic", "source_secret": "private"}, "source_emails": [], "paperless_documents": []}
        answer = {
            "analysis": "A short synthetic summary.",
            "recommended_actions": ["Confirm the appointment."],
            "response_subject": "Re: Appointment",
            "response_body": "Thanks, I will confirm.",
            "confidence": "medium",
        }
        routed = {"provider": "ollama", "privacy": "local-only", "text": json.dumps(answer)}
        with patch.object(RECONCILER, "_review_context", return_value=evidence), \
             patch.object(RECONCILER.ai_broker, "generate", return_value=routed) as generate:
            result = RECONCILER._build_task_review({"id": "synthetic-task"})
        self.assertEqual(generate.call_args.kwargs["privacy"], "local-only")
        self.assertEqual(generate.call_args.kwargs["force_provider"], "ollama")
        self.assertNotIn("source_emails", result)
        self.assertNotIn("paperless_documents", result)
        self.assertNotIn("source_secret", str(result))

    def test_rejects_any_non_local_ai_route(self):
        answer = {"analysis": "x", "recommended_actions": [], "response_subject": "", "response_body": "", "confidence": "low"}
        with patch.object(RECONCILER, "_review_context", return_value={}), \
             patch.object(RECONCILER.ai_broker, "generate", return_value={"provider": "remote", "privacy": "local-only", "text": json.dumps(answer)}):
            with self.assertRaisesRegex(RuntimeError, "review_provider_not_local"):
                RECONCILER._build_task_review({"id": "synthetic-task"})

    def test_saved_review_contains_no_source_context(self):
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory)
            with patch.object(RECONCILER, "REVIEW_RESULTS", results):
                RECONCILER._save_task_review("synthetic-task", {
                    "schema": "lifeos_pa_task_review_v1", "analysis": "summary",
                    "recommended_actions": [], "response_subject": "", "response_body": "",
                    "confidence": "low", "generated_at": 1,
                })
            saved = json.loads((results / "synthetic-task.json").read_text())
            self.assertNotIn("source_emails", saved)
            self.assertNotIn("paperless_documents", saved)


if __name__ == "__main__":
    unittest.main()
