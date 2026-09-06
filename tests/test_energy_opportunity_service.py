import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = (
    ROOT
    / "homelab/live/mnt/docker-data/automation/repos/LifeOS-Energy"
)
sys.path.insert(0, str(SERVICE_ROOT))
M = importlib.import_module("app.services.opportunities")


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
