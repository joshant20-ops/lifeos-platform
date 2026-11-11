import io
import unittest
from unittest.mock import patch

from governor.mqtt_log_review import local_review, summarize


class LogReviewTests(unittest.TestCase):
    def test_full_closed_file_includes_unknowns_and_bounds_examples(self):
        source = b"10: New client connected\n" + b"11: Error in broker\n" * 12 + b"12: unfamiliar\n"
        report = summarize(io.BytesIO(source), len(source), closed=True)
        self.assertEqual(report["end_offset"], len(source))
        self.assertEqual(report["counts"], {"connection": 1, "errors": 12, "unknown": 1})
        self.assertEqual(len(report["samples"]["errors"]), 4)

    def test_live_scan_revisits_partial_last_record(self):
        source = b"one\ntwo"
        self.assertEqual(summarize(io.BytesIO(source), len(source), closed=False)["end_offset"], 4)

    def test_model_request_is_local_only_and_has_no_tool_authority(self):
        with patch("governor.mqtt_log_review.generate", return_value={
            "provider": "ollama", "model": "synthetic", "privacy": "local-only",
            "text": '{"summary":"No issue found","findings":[]}',
        }) as generate:
            result = local_review({"counts": {}, "samples": {}})
        self.assertEqual(result["findings"], [])
        self.assertEqual(generate.call_args.kwargs["privacy"], "local-only")
        self.assertEqual(generate.call_args.kwargs["force_provider"], "ollama")
