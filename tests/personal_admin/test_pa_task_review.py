"""Privacy and queue checks for local task review."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = ROOT / "homelab" / "live" / "home" / "joshan" / "automation"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AUTOMATION))
SPEC = importlib.util.spec_from_file_location("lifeos_task_review_tests", AUTOMATION / "lifeos_task_reconciler.py")
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


class PATaskReviewTests(unittest.TestCase):
    def test_review_rediscovers_and_persists_only_verified_paperless_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_id = "synthetic-task"
            state = root / "state.json"
            output = root / "www" / "lifeos_tasks.json"
            output.parent.mkdir()
            task = {
                "id": task_id,
                "title": "Synthetic order update",
                "email_message_id": "<order@example.test>",
                "source_message_ids": ["<order@example.test>"],
                "case_reference_ids": [],
                "paperless_evidence": [],
            }
            payload = {"tasks": [task], "resolved": []}
            state.write_text(json.dumps(payload))
            output.write_text(json.dumps(payload))

            requests = root / "review-requests"
            requests.mkdir()
            request = requests / f"{task_id}.json"
            request.write_text(json.dumps({
                "schema": "lifeos_pa_review_request_v1",
                "task_id": task_id,
                "request_id": "a" * 32,
            }))
            results = root / "task-reviews"
            previews = root / "task-previews"

            def document(document_id):
                return {
                    "id": document_id,
                    "title": "Verified source email" if document_id == 41 else "Unrelated result",
                    "created": "2026-10-21",
                    "content": "Message-ID: <order@example.test>" if document_id == 41 else "Message-ID: <other@example.test>",
                }

            answer = {
                "analysis": "Synthetic review.",
                "recommended_actions": ["Check the order status."],
                "response_subject": "Re: Order",
                "response_body": "Thanks for the update.",
                "confidence": "medium",
            }
            routed = {"provider": "ollama", "privacy": "local-only", "text": json.dumps(answer)}
            patches = [
                patch.object(RECONCILER, "STATE", state),
                patch.object(RECONCILER, "OUT", output),
                patch.object(RECONCILER, "REVIEW_REQUESTS", requests),
                patch.object(RECONCILER, "REVIEW_FAILED", requests / "failed"),
                patch.object(RECONCILER, "REVIEW_RESULTS", results),
                patch.object(RECONCILER, "REVIEW_PREVIEWS", previews),
                patch.object(RECONCILER, "paperless_search", return_value=[
                    {"document_id": 41, "title": "Candidate"},
                    {"document_id": 42, "title": "Unrelated candidate"},
                ]),
                patch.object(RECONCILER, "_paperless_document", side_effect=document),
                patch.object(RECONCILER, "_review_context", side_effect=lambda current: {
                    "task": current,
                    "source_emails": [],
                    "paperless_documents": [{"document_id": str(x["document_id"]), "title": x["title"], "ocr_text": "verified text"} for x in current["paperless_evidence"]],
                }),
                patch.object(RECONCILER.ai_broker, "generate", return_value=routed),
            ]
            with ExitStack() as stack:
                generate = None
                for item in patches:
                    entered = stack.enter_context(item)
                    if item is patches[-1]:
                        generate = entered
                RECONCILER.process_task_review_requests()

            self.assertFalse(request.exists())
            self.assertEqual(generate.call_args.kwargs["force_provider"], "ollama")
            self.assertEqual(generate.call_args.kwargs["privacy"], "local-only")
            self.assertEqual([x["document_id"] for x in json.loads(state.read_text())["tasks"][0]["paperless_evidence"]], [41])
            self.assertEqual([x["document_id"] for x in json.loads(output.read_text())["tasks"][0]["paperless_evidence"]], [41])
            preview = json.loads((previews / f"{task_id}.json").read_text())
            self.assertEqual([x["document_id"] for x in preview["documents"]], ["41"])

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

    def test_document_text_preview_is_bounded_and_owner_only(self):
        with tempfile.TemporaryDirectory() as directory:
            previews = Path(directory)
            with patch.object(RECONCILER, "REVIEW_PREVIEWS", previews):
                RECONCILER._save_task_previews("synthetic-task", {
                    "paperless_documents": [{
                        "document_id": "42", "title": "Synthetic letter", "ocr_text": "private text",
                    }],
                })
            path = previews / "synthetic-task.json"
            saved = json.loads(path.read_text())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(saved["documents"][0]["ocr_text"], "private text")
            self.assertLessEqual(len(saved["documents"][0]["ocr_text"]), 5000)
            self.assertNotIn("source_emails", saved)

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
