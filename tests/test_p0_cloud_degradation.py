from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from governor import ha_issue_queue_bridge


SCRIPT = "homelab/live/usr/local/sbin/lifeos-powerdown-assurance-active"


class QueueRetryTests(unittest.TestCase):
    def test_retry_is_exponential_and_capped(self):
        self.assertEqual(
            [ha_issue_queue_bridge.retry_delay(n) for n in range(1, 7)],
            [30, 60, 120, 240, 480, 900],
        )
        self.assertEqual(ha_issue_queue_bridge.retry_delay(30), 900)


class PowerDownDegradationTests(unittest.TestCase):
    def run_with_event_response(self, response_or_error):
        with tempfile.TemporaryDirectory() as tempdir:
            env = {
                "HA_TOKEN": "test-token",
                "LIFEOS_POWERDOWN_ROOT": tempdir,
            }
            output = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False):
                if isinstance(response_or_error, BaseException):
                    urlopen_patch = mock.patch.object(
                        urllib.request, "urlopen", side_effect=response_or_error
                    )
                else:
                    urlopen_patch = mock.patch.object(
                        urllib.request, "urlopen", return_value=response_or_error
                    )
                with urlopen_patch:
                    with contextlib.redirect_stdout(output):
                        with self.assertRaises(SystemExit) as result:
                            runpy.run_path(SCRIPT, run_name="p0_powerdown_test")
            status_path = os.path.join(tempdir, "active-status.json")
            status = None
            if os.path.exists(status_path):
                with open(status_path, encoding="utf-8") as handle:
                    status = json.load(handle)
            return result.exception.code, status, output.getvalue()

    def test_missing_event_entity_is_expected_degradation(self):
        code, status, output = self.run_with_event_response(
            urllib.error.HTTPError(
                "http://127.0.0.1/api/states/event.octopus",
                404,
                "Not Found",
                {},
                None,
            )
        )
        self.assertEqual(code, 0)
        self.assertEqual(status["state"], "DEGRADED")
        self.assertEqual(status["degradation"]["code"], "WAN_UNAVAILABLE")
        self.assertFalse(status["control"]["write_performed"])
        self.assertIn("CONTROLLER_STATUS=DEGRADED", output)

    def test_unavailable_event_state_is_expected_degradation(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = b'{"state":"unavailable"}'
        code, status, _ = self.run_with_event_response(response)
        self.assertEqual(code, 0)
        self.assertEqual(status["degradation"]["reason"], "cloud_entity_unavailable")
        self.assertFalse(status["control"]["write_performed"])

    def test_authentication_error_still_fails(self):
        error = urllib.error.HTTPError(
            "http://127.0.0.1/api/states/event.octopus",
            401,
            "Unauthorized",
            {},
            None,
        )
        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.dict(
                os.environ,
                {"HA_TOKEN": "test-token", "LIFEOS_POWERDOWN_ROOT": tempdir},
                clear=False,
            ):
                with mock.patch.object(urllib.request, "urlopen", side_effect=error):
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        runpy.run_path(SCRIPT, run_name="p0_powerdown_auth_test")
        self.assertEqual(raised.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
