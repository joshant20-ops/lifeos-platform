from __future__ import annotations

from datetime import date
from pathlib import Path

import app.services.history as history
import app.services.octopus as octopus


def _insert_raw_sample(reading_time: int, *, grid_import: float = 500, battery: float = -200) -> None:
    with history.connect() as connection:
        connection.execute(
            """INSERT INTO telemetry
               (reading_time,production_w,consumption_w,grid_w,grid_import_w,
                grid_export_w,battery_soc_percent,battery_power_w,source,provider,recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (reading_time, 1000.0, 700.0, 500.0, grid_import, 0.0, 50.0, battery,
             "enphase", "test", reading_time),
        )


def test_compaction_preserves_usage_and_domestic_import_idempotently(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(history, "DATABASE_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(history, "RAW_RETENTION_HOURS", 1)
    monkeypatch.setattr(history, "COLLECTION_INTERVAL_SECONDS", 300)
    history.initialise_database()
    bucket = 4_000_000_000 - (4_000_000_000 % 1800)
    _insert_raw_sample(bucket)
    _insert_raw_sample(bucket + 300)

    history.compact_history(now=bucket + 4500)
    history.compact_history(now=bucket + 4800)

    with history.connect() as connection:
        row = connection.execute(
            "SELECT sample_count,production_wh,grid_import_wh,domestic_import_wh "
            "FROM energy_rollup_30m WHERE bucket_start=?",
            (bucket,),
        ).fetchone()
        raw_count = connection.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]

    assert row["sample_count"] == 2
    assert row["production_wh"] == 2 * 1000 * 300 / 3600
    assert row["grid_import_wh"] == 2 * 500 * 300 / 3600
    assert row["domestic_import_wh"] == 2 * (500 - 200) * 300 / 3600
    assert raw_count == 0


def test_rollup_cost_uses_domestic_import_and_octopus_rate(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(history, "DATABASE_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(history, "load_config", lambda: {"site": {"timezone": "Europe/London"}})
    history.initialise_database()
    timestamp = 1_800_000_000
    with history.connect() as connection:
        connection.execute(
            """INSERT INTO energy_rollup_30m
               (bucket_start,sample_count,production_wh,consumption_wh,grid_import_wh,
                grid_export_wh,battery_charge_wh,battery_discharge_wh,domestic_import_wh)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (timestamp, 30, 1000, 800, 500, 100, 50, 10, 300),
        )
    monkeypatch.setattr(
        "app.services.octopus.account_tariffs",
        lambda: {"import": {"tariff_code": "E-1R-TEST-1-A"}},
    )
    monkeypatch.setattr(
        "app.services.octopus.tariff_prices_range",
        lambda code, start, end, zone: {timestamp: 25.0},
    )

    result = history.read_rollups(timestamp, timestamp + 1800, "30m")
    point = result["points"][0]
    assert point["grid_import_kwh"] == 0.0005
    assert point["domestic_import_kwh"] == 0.0003
    assert point["import_p_per_kwh"] == 25.0
    assert point["domestic_import_cost_gbp"] == 0.000075
    assert result["totals"]["domestic_import_cost_gbp"] == 0.000075


def test_missing_octopus_price_is_explicit_not_zero(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(history, "DATABASE_PATH", tmp_path / "history.sqlite3")
    monkeypatch.setattr(history, "load_config", lambda: {"site": {"timezone": "Europe/London"}})
    history.initialise_database()
    timestamp = 1_800_000_000
    with history.connect() as connection:
        connection.execute(
            """INSERT INTO energy_rollup_30m
               (bucket_start,sample_count,production_wh,consumption_wh,grid_import_wh,
                grid_export_wh,battery_charge_wh,battery_discharge_wh,domestic_import_wh)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (timestamp, 30, 1000, 800, 500, 100, 50, 10, 300),
        )
    monkeypatch.setattr(
        "app.services.octopus.account_tariffs",
        lambda: {"import": {"tariff_code": "E-1R-TEST-1-A"}},
    )
    monkeypatch.setattr(
        "app.services.octopus.tariff_prices_range",
        lambda code, start, end, zone: {},
    )

    point = history.read_rollups(timestamp, timestamp + 1800)["points"][0]
    assert point["import_price_available"] is False
    assert point["domestic_import_cost_gbp"] is None


def test_octopus_range_uses_local_dst_day_boundaries(monkeypatch) -> None:
    seen = {}

    def fake_request(url, params=None, authenticated=False):
        seen["params"] = params
        return {
            "results": [
                {"valid_from": "2026-03-29T00:00:00Z", "value_inc_vat": 23.5}
            ],
            "next": None,
        }

    monkeypatch.setattr(octopus, "_request_json", fake_request)
    rates = octopus.tariff_prices_range(
        "E-1R-TEST-1-A", date(2026, 3, 29), date(2026, 3, 29), "Europe/London"
    )

    assert seen["params"]["period_from"] == "2026-03-29T00:00:00Z"
    assert seen["params"]["period_to"] == "2026-03-29T23:00:00Z"
    assert rates
