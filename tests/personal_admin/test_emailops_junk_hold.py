"""A shadow evaluation must preserve pending choices without replaying mutations."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = ROOT / "homelab/live/home/joshan/automation"
sys.path.insert(0, str(AUTOMATION))
SPEC = importlib.util.spec_from_file_location("emailops_hold_reconciler", AUTOMATION / "lifeos_task_reconciler.py")
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


class JunkShadowHoldTests(unittest.TestCase):
    def test_shadow_holds_exact_document_selection_without_calling_processors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config/emailops-upstream.json").write_text('{"mode":"shadow","mailbox_writes":false}')
            pending, failed = root / "pending", root / "failed"
            pending.mkdir()
            selected = {"task_id": "synthetic", "paperless_document_ids": [41]}
            (pending / "synthetic.json").write_text(json.dumps(selected))
            with patch.object(RECONCILER, "REPO", root), patch.object(RECONCILER, "JUNK_REQUESTS", pending), \
                 patch.object(RECONCILER, "JUNK_FAILED", failed), patch.object(RECONCILER, "_process_junk_request") as process:
                RECONCILER.process_junk_requests()
            process.assert_not_called()
            self.assertEqual(list(pending.glob("*.json")), [])
            held = list((failed / "held").glob("*/*.json"))
            self.assertEqual(len(held), 1)
            self.assertEqual(json.loads(held[0].read_text()), selected)
