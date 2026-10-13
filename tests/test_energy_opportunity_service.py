import importlib
import json
import sqlite3
import sys
import tempfile
import unittest
from io import BytesIO
from urllib.error import HTTPError
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = (
    ROOT
    / "homelab/live/mnt/docker-data/automation/repos/LifeOS-Energy"
)
sys.path.insert(0, str(SERVICE_ROOT))
M = importlib.import_module("app.services.opportunities")
CACHE = importlib.import_module("app.services.octopus_cache")
OCTOPUS = importlib.import_module("app.services.octopus")


class OctopusTariffCacheTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        CACHE.initialise(self.connection)
        self.now = 1_800_000_000
        self.tariff = "E-1R-AGILE-FLEX-22-11-25-J"

    def tearDown(self):
        self.connection.close()

    def test_tariff_code_and_prices_are_reused_from_sqlite(self):
        calls = {"account": 0, "prices": 0}

        def fetch_code():
            calls["account"] += 1
            return self.tariff

        def fetch_prices():
            calls["prices"] += 1
            return {1000: 25.0, 2800: 30.0}

        code, account_status, _ = CACHE.import_tariff_code(
            self.connection, now=self.now, fetch_tariff_code=fetch_code
        )
        rates, price_status, age, failed = CACHE.tariff_rates(
            self.connection, code, [1000, 2800], now=self.now,
            fetch_rates=fetch_prices,
        )
        self.assertEqual(account_status, "fresh")
        self.assertEqual(price_status, "fresh")
        self.assertEqual(rates, {1000: 25.0, 2800: 30.0})
        self.assertEqual(age, 0)
        self.assertFalse(failed)

        code, account_status, _ = CACHE.import_tariff_code(
            self.connection, now=self.now + 60,
            fetch_tariff_code=lambda: self.fail("fresh account cache should be used"),
        )
        rates, price_status, _, failed = CACHE.tariff_rates(
            self.connection, code, [1000, 2800], now=self.now + 60,
            fetch_rates=lambda: self.fail("fresh price cache should be used"),
        )
        self.assertEqual(account_status, "cached")
        self.assertEqual(price_status, "cached")
        self.assertEqual(rates, {1000: 25.0, 2800: 30.0})
        self.assertFalse(failed)
        self.assertEqual(calls, {"account": 1, "prices": 1})

    def test_stale_rates_are_used_when_octopus_is_temporarily_unavailable(self):
        code, _, _ = CACHE.import_tariff_code(
            self.connection, now=self.now,
            fetch_tariff_code=lambda: self.tariff,
        )
        rates, _, _, _ = CACHE.tariff_rates(
            self.connection, code, [1000, 2800], now=self.now,
            fetch_rates=lambda: {1000: 25.0, 2800: 30.0},
        )
        stale_at = self.now + CACHE.PRICE_CACHE_TTL_SECONDS + 1
        rates, status, age, failed = CACHE.tariff_rates(
            self.connection, code, [1000, 2800], now=stale_at,
            fetch_rates=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
        )
        self.assertEqual(status, "stale_cache")
        self.assertEqual(rates, {1000: 25.0, 2800: 30.0})
        self.assertGreater(age, CACHE.PRICE_CACHE_TTL_SECONDS)
        self.assertTrue(failed)

    def test_datetime_time_remains_available_for_tariff_boundaries(self):
        self.assertIs(OCTOPUS.time, datetime_time)
        self.assertEqual(OCTOPUS.time.min, datetime_time.min)

    def test_transient_octopus_http_error_is_retried(self):
        failure = HTTPError(
            "https://api.octopus.energy/v1/example",
            503,
            "temporarily unavailable",
            {"Retry-After": "0"},
            BytesIO(b""),
        )
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"available": true}'
        with (
            patch.object(OCTOPUS, "urlopen", side_effect=[failure, response]) as request,
            patch.object(OCTOPUS._time, "sleep"),
        ):
            result = OCTOPUS._request_json("https://api.octopus.energy/v1/example")
        self.assertEqual(result, {"available": True})
        self.assertEqual(request.call_count, 2)


class EnergyOpportunityServiceTests(unittest.TestCase):
    def test_groups_negative_slots_and_preserves_stable_identity(self):
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        slots = [
            M.RateSlot(start, start + timedelta(minutes=30), -1.0),
            M.RateSlot(
                start + timedelta(minutes=30),
                start + timedelta(minutes=60),
                -3.0,
            ),
        ]
        first = M.group_negative_import_slots(
            slots, detected_at=start
        )[0]
        replay = M.group_negative_import_slots(
            slots, detected_at=start + timedelta(hours=1)
        )[0]
        self.assertEqual(first.opportunity_id, replay.opportunity_id)
        self.assertEqual(first.duration_minutes, 60)
        self.assertEqual(first.minimum_price_p_per_kwh, -3.0)

    def test_projection_collapses_duplicate_identity(self):
        row = {
            "opportunity_id": "negative-import-stable",
            "severity": "opportunity",
            "start": "2026-09-06T00:00:00+00:00",
            "end": "2026-09-06T00:30:00+00:00",
            "minimum_price_p_per_kwh": -2.0,
            "source": M.SOURCE,
        }
        projection = M.build_projection([row, dict(row)])
        self.assertEqual(
            projection["opportunity_ids"], ["negative-import-stable"]
        )
        self.assertEqual(projection["attention_id"], "negative-import-stable")
        self.assertEqual(projection["count"], 1)
        self.assertEqual(len(projection["opportunities"]), 1)

    def test_refresh_persists_current_and_deduplicated_history(self):
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        slots = [M.RateSlot(start, start + timedelta(minutes=30), -1.0)]
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "current.json"
            ledger = Path(directory) / "ledger.json"
            with (
                patch.object(M, "CURRENT_PATH", current),
                patch.object(M, "LEDGER_PATH", ledger),
                patch.object(M, "_price_slots", return_value=slots),
            ):
                first = M.refresh_opportunities("UTC")
                first_history = json.loads(ledger.read_text())
                second = M.refresh_opportunities("UTC")
            self.assertEqual(first["attention_id"], second["attention_id"])
            history = json.loads(ledger.read_text())
            self.assertEqual(list(history), [first["attention_id"]])
            self.assertEqual(
                history[first["attention_id"]]["first_detected_at"],
                first_history[first["attention_id"]]["first_detected_at"],
            )

    def test_clear_projection_matches_ha_contract(self):
        projection = M.build_projection([])
        self.assertEqual(projection["state"], "clear")
        self.assertEqual(projection["count"], 0)
        self.assertEqual(projection["opportunity_ids"], [])


if __name__ == "__main__":
    unittest.main()
