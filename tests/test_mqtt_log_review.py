import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from governor.mqtt_event_metadata import event_metadata
from governor.mqtt_log_review import local_review, review_batches, summarize


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
        schema = generate.call_args.kwargs["response_format"]
        self.assertEqual(schema["required"], ["summary", "findings"])
        self.assertEqual(schema["properties"]["findings"]["items"]["type"], "string")

    def test_batches_finish_records_and_resume_only_unfinished_inference(self):
        source = b"alpha\nbeta\n"
        manifest = {"start_offset": 0, "target_offset": len(source)}
        expected = {"provider": "ollama", "summary": "fixture", "findings": []}
        calls = []

        def inference(evidence):
            calls.append(evidence["start_offset"])
            if calls == [0, 6]:
                raise RuntimeError("temporary provider failure")
            return expected

        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory) / "report.json"
            def run():
                return review_batches(io.BytesIO(source), path, manifest,
                                      closed=True, reserve=lambda: None, stable=lambda: None,
                                      inference=inference, batch_bytes=5)
            with self.assertRaisesRegex(RuntimeError, "temporary provider failure"):
                run()
            with patch("governor.mqtt_log_review.summarize", side_effect=AssertionError("rescanned")):
                evidence, batches = run()
        self.assertEqual(calls, [0, 6, 6])
        self.assertEqual(evidence["end_offset"], len(source))
        self.assertEqual([(item["start_offset"], item["end_offset"]) for item in batches],
                         [(0, 6), (6, len(source))])

    def test_records_observed_peer_destination_and_gmt_time(self):
        raw = b"0: New connection from 172.21.0.1:1234 on port 1883.\n"
        report = summarize(io.BytesIO(raw), len(raw), closed=True)
        self.assertEqual(report["first_record_time_gmt"], "1970-01-01 00:00:00 GMT")
        self.assertEqual(report["samples"]["connection"], [{
            "id": "0", "time_gmt": "1970-01-01 00:00:00 GMT",
            "event": "socket_connection", "source": {"observed_peer": "172.21.0.1:1234"},
            "destination": {"broker_listener_port": 1883}, "topic": None,
        }])

    def test_publish_direction_does_not_invent_original_publisher_or_export_payload(self):
        raw = b"1: Sending PUBLISH to test-client (d0, q0, r0, m0, 'test/topic', ... (3 bytes)) secret"
        event = event_metadata(raw)
        self.assertEqual(event["source"], {"role": "broker"})
        self.assertEqual(event["destination"], {"client_id": "test-client"})
        self.assertEqual(event["topic"], "test/topic")
        self.assertNotIn("secret", str(event))
        incoming = event_metadata(raw.replace(b"Sending PUBLISH to", b"Received PUBLISH from"))
        self.assertEqual(incoming["source"], {"client_id": "test-client"})
        self.assertEqual(incoming["destination"], {"role": "broker"})

    def test_unknown_route_is_explicit(self):
        event = event_metadata(b"1: Some unexpected event")
        self.assertIsNone(event["source"])
        self.assertIsNone(event["destination"])
        self.assertIsNone(event["topic"])
