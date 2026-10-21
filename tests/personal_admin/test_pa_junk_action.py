from pathlib import Path
import importlib.util
import json
import tempfile
import sys
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess

ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = ROOT / "homelab" / "live" / "home" / "joshan" / "automation"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AUTOMATION))
SPEC = importlib.util.spec_from_file_location(
    "lifeos_task_reconciler_junk_tests",
    AUTOMATION / "lifeos_task_reconciler.py",
)
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


class PAJunkActionTests(unittest.TestCase):
    def setUp(self):
        self.task = {
            "id": "matter-1234",
            "status": "OPEN",
            "email_message_id": "<latest@example.test>",
            "source_message_ids": ["<older@example.test>", "<latest@example.test>"],
            "paperless_evidence": [
                {"document_id": 41, "title": "Selected record"},
                {"document_id": 42, "title": "Other candidate"},
            ],
        }
        self.request = {
            "schema": "lifeos_pa_junk_request_v1",
            "request_id": "a" * 32,
            "task_id": "matter-1234",
            "paperless_document_ids": [41],
            "requested_at": 1,
        }

    def run_request(self, request):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / (request["task_id"] + ".json")
            path.write_text(json.dumps(request), encoding="utf-8")
            RECONCILER._process_junk_request(path)

    def test_only_explicitly_selected_linked_document_is_deleted(self):
        with patch.object(RECONCILER, "load_previous", return_value={self.task["id"]: self.task}), \
             patch.object(RECONCILER, "_paperless_document", return_value={"id": 41}), \
             patch.object(RECONCILER, "_move_emails_to_junk") as move, \
             patch.object(RECONCILER, "_paperless_delete") as delete, \
             patch.object(RECONCILER.subprocess, "run", return_value=CompletedProcess([], 0, "PA_USER_ACTION=PASS", "")) as dismiss:
            self.run_request(self.request)
        move.assert_called_once_with(["<latest@example.test>", "<older@example.test>"])
        delete.assert_called_once_with(41)
        self.assertEqual(dismiss.call_count, 1)

    def test_unselected_paperless_candidate_is_not_deleted(self):
        self.request["paperless_document_ids"] = [41, 999]
        with patch.object(RECONCILER, "load_previous", return_value={self.task["id"]: self.task}), \
             patch.object(RECONCILER, "_paperless_document") as get_document, \
             patch.object(RECONCILER, "_move_emails_to_junk") as move, \
             patch.object(RECONCILER, "_paperless_delete") as delete:
            with self.assertRaisesRegex(ValueError, "paperless_selection_not_linked"):
                self.run_request(self.request)
        get_document.assert_not_called()
        move.assert_not_called()
        delete.assert_not_called()

    def test_missing_stable_email_reference_fails_before_external_mutations(self):
        self.task["source_message_ids"] = ["uidvalidity:77"]
        self.task["email_message_id"] = ""
        with patch.object(RECONCILER, "load_previous", return_value={self.task["id"]: self.task}), \
             patch.object(RECONCILER, "_paperless_document") as get_document, \
             patch.object(RECONCILER, "_move_emails_to_junk") as move, \
             patch.object(RECONCILER, "_paperless_delete") as delete:
            with self.assertRaisesRegex(ValueError, "source_email_id_invalid"):
                RECONCILER._process_junk_request(self.request)
        get_document.assert_not_called()
        move.assert_not_called()
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
