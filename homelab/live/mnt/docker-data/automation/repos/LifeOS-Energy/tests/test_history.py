
from __future__ import annotations

from pathlib import Path

import app.services.history as history


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
