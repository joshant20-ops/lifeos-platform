from hashlib import sha256
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import call, patch

from governor.mqtt_log_review import ReviewOutputInvalid, ReviewUnverified
from governor.mqtt_nas_reanalysis import ForwardStream, reanalyse, review_archive_batch
from governor.mqtt_retained_log_archive import ARCHIVE_NAME


class NASReanalysisTests(unittest.TestCase):
    @patch("governor.mqtt_nas_reanalysis.local_review")
    def test_invalid_output_retries_once_with_shorter_target(self, review):
        evidence = {"counts": {"connection": 10}}
        validated = {"provider": "ollama", "summary": "Connection burst.", "findings": []}
        review.side_effect = [ReviewOutputInvalid("structured_review_invalid"), validated]
        self.assertEqual(review_archive_batch(evidence), validated)
        self.assertEqual(review.call_args_list, [call(evidence), call(evidence, concise=True)])

    @patch("governor.mqtt_nas_reanalysis.local_review")
    def test_persistent_invalid_output_fails_after_two_attempts(self, review):
        review.side_effect = ReviewOutputInvalid("structured_review_invalid")
        with self.assertRaises(ReviewOutputInvalid):
            review_archive_batch({})
        self.assertEqual(review.call_count, 2)

    @patch("governor.mqtt_nas_reanalysis.local_review")
    def test_provider_verification_failure_never_retries(self, review):
        review.side_effect = ReviewUnverified("local_provider_unverified")
        with self.assertRaises(ReviewUnverified):
            review_archive_batch({})
        review.assert_called_once_with({})

    def test_skipped_bytes_still_contribute_to_the_archive_digest(self):
        data = b"one\ntwo\nthree\n"
        stream = ForwardStream(io.BytesIO(data), len(data))
        self.assertEqual(stream.readline(4), b"one\n")
        stream.seek(8)
        self.assertEqual(stream.readline(6), b"three\n")
        stream.verify(sha256(data).hexdigest())

    def test_rejects_short_or_wrong_archive(self):
        with self.assertRaisesRegex(ReviewUnverified, "archive_stream_short"):
            ForwardStream(io.BytesIO(b"abc"), 5).verify("invalid")
        with self.assertRaisesRegex(ReviewUnverified, "archive_stream_digest_mismatch"):
            ForwardStream(io.BytesIO(b"abc"), 3).verify("invalid")

    @unittest.skipUnless(shutil.which("restic"), "requires Restic")
    def test_reanalyse_encrypted_fixture_with_no_restored_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {**os.environ, "RESTIC_REPOSITORY": str(root / "repository"),
                   "RESTIC_PASSWORD": "synthetic-fixture"}
            data = b"1: New connection from 127.0.0.1:54321 on port 1883.\n"
            tag = "mqtt-retained-" + sha256(data).hexdigest()
            subprocess.run(["restic", "--no-cache", "init"], env=env, check=True,
                           stdout=subprocess.DEVNULL, timeout=30)
            subprocess.run(["restic", "--no-cache", "backup", "--stdin",
                            "--stdin-filename", ARCHIVE_NAME, "--tag", tag],
                           env=env, input=data, check=True, stdout=subprocess.DEVNULL, timeout=30)
            proof = {"archive_tag": tag, "fingerprint": [1, 2, len(data)]}
            def review(evidence):
                self.assertEqual(evidence["samples"]["connection"][0]["destination"],
                                 {"broker_listener_port": 1883})
                return {"provider": "ollama", "summary": "synthetic", "findings": []}
            result = reanalyse(env, proof, root, inference=review)
            self.assertEqual(result["reviewed_bytes"], len(data))
            self.assertEqual(result["status"], "nas_metadata_review_verified")
            self.assertFalse((root / ARCHIVE_NAME).exists())
