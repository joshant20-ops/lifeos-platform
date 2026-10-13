
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import app.services.history as history
import app.services.octopus as octopus


def test_insert_and_read_history(tmp_path: Path) -> None:
    original = history.DATABASE_PATH
    history.DATABASE_PATH = tmp_path / "history.sqlite3"

    try:
        history.initialise_database()

        history.insert_telemetry(
            {
                "reading_time": 4_000_000_000,
                "production_w": 1000.0,
                "consumption_w": 800.0,
                "grid_w": -200.0,
                "grid_import_w": 0.0,
                "grid_export_w": 200.0,
                "battery": {
                    "soc_percent": 55.0,
                    "power_w": -100.0,
                },
                "source": "test",
                "provider": "test",
            }
        )

        result = history.read_history(168)

        assert len(result) == 1
        assert result[0]["production_w"] == 1000.0
        assert result[0]["battery_soc_percent"] == 55.0
        assert result[0]["battery_power_w"] == -100.0

    finally:
        history.DATABASE_PATH = original


def test_octopus_tariff_range_uses_london_dst_boundaries(monkeypatch) -> None:
    requests: list[dict[str, str]] = []

    def fake_request(url: str, params: dict[str, str] | None = None, authenticated: bool = False):
        assert params is not None
        requests.append(params)
        return {"results": [], "next": None}

    monkeypatch.setattr(octopus, "_product_from_tariff", lambda _: "PRODUCT")
    monkeypatch.setattr(octopus, "_request_json", fake_request)

    for target_date, expected_hours in (
        (date(2026, 3, 29), 23),
        (date(2026, 10, 25), 25),
    ):
        octopus.tariff_prices_range(
            "E-1R-TEST-AGILE-FLEX-22-11-25-A", target_date, target_date, "Europe/London"
        )
        period = requests[-1]
        start = datetime.fromisoformat(period["period_from"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(period["period_to"].replace("Z", "+00:00"))
        assert start.utcoffset().total_seconds() == 0
        assert end.utcoffset().total_seconds() == 0
        assert (end - start).total_seconds() == expected_hours * 3600
