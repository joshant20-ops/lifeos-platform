
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


def _insert_raw_sample(reading_time: int) -> None:
    with history.connect() as connection:
        connection.execute(
            """INSERT INTO telemetry
               (reading_time,production_w,consumption_w,grid_w,grid_import_w,
                grid_export_w,battery_soc_percent,battery_power_w,source,provider,recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (reading_time,1000.0,500.0,0.0,100.0,0.0,50.0,0.0,"test","test",reading_time),
        )


def test_compaction_accumulates_samples_aging_out_at_different_times(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(history, "DATABASE_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(history, "RAW_RETENTION_HOURS", 1)
    monkeypatch.setattr(history, "COLLECTION_INTERVAL_SECONDS", 300)
    history.initialise_database()

    bucket = 4_000_000_000 - (4_000_000_000 % 1800)
    _insert_raw_sample(bucket)
    _insert_raw_sample(bucket + 300)

    history.compact_history(now=bucket + 3750)  # cutoff is bucket + 150
    history.compact_history(now=bucket + 4050)  # cutoff is bucket + 450

    with history.connect() as connection:
        row = connection.execute(
            "SELECT sample_count,production_wh FROM energy_rollup_30m WHERE bucket_start=?",
            (bucket,),
        ).fetchone()

    assert row["sample_count"] == 2
    assert abs(row["production_wh"] - (2 * 1000.0 * 300 / 3600)) < 1e-6


def test_daily_compaction_accumulates_buckets_aging_out_at_different_times(
    monkeypatch, tmp_path: Path
) -> None:
    from datetime import datetime, timezone

    monkeypatch.setattr(history, "DATABASE_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(history, "RAW_RETENTION_HOURS", 1)
    monkeypatch.setattr(history, "HALF_HOUR_RETENTION_DAYS", 1)
    history.initialise_database()

    day = int(datetime(2023, 11, 14, tzinfo=timezone.utc).timestamp())
    with history.connect() as connection:
        connection.executemany(
            """INSERT INTO energy_rollup_30m VALUES (?,?,?,?,?,?,?,?)""",
            [
                (day, 1, 100.0, 200.0, 30.0, 10.0, 5.0, 2.0),
                (day + 1800, 1, 200.0, 300.0, 40.0, 20.0, 6.0, 3.0),
            ],
        )

    history.compact_history(now=day + 86400 + 900)
    history.compact_history(now=day + 86400 + 2700)

    with history.connect() as connection:
        row = connection.execute(
            "SELECT sample_count,production_wh,grid_import_wh FROM energy_rollup_daily WHERE day_start=?",
            (day,),
        ).fetchone()

    assert row["sample_count"] == 2
    assert row["production_wh"] == 300.0
    assert row["grid_import_wh"] == 70.0
