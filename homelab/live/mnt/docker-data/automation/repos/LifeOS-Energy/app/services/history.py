from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config import load_config
from app.services.enphase import (
    EnphaseAuthenticationError,
    EnphaseClient,
    EnphaseUnavailableError,
)


DATABASE_PATH = Path(
    os.getenv("ENERGY_HISTORY_DATABASE", "/data/lifeos-energy-history.sqlite3")
)
COLLECTION_INTERVAL_SECONDS = max(
    30, int(os.getenv("ENERGY_COLLECTION_INTERVAL_SECONDS", "60"))
)
RAW_RETENTION_HOURS = max(842, int(os.getenv("ENERGY_RAW_RETENTION_HOURS", "842")))

_client = EnphaseClient()
_collector_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def initialise_database() -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                reading_time INTEGER PRIMARY KEY,
                production_w REAL NOT NULL,
                consumption_w REAL,
                grid_w REAL,
                grid_import_w REAL NOT NULL,
                grid_export_w REAL NOT NULL,
                battery_soc_percent REAL,
                battery_power_w REAL,
                source TEXT NOT NULL,
                provider TEXT NOT NULL,
                recorded_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_recorded_at ON telemetry(recorded_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS energy_rollup_30m (
                bucket_start INTEGER PRIMARY KEY,
                sample_count INTEGER NOT NULL,
                production_wh REAL NOT NULL,
                consumption_wh REAL NOT NULL,
                grid_import_wh REAL NOT NULL,
                grid_export_wh REAL NOT NULL,
                battery_charge_wh REAL NOT NULL,
                battery_discharge_wh REAL NOT NULL,
                domestic_import_wh REAL NOT NULL DEFAULT 0
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(energy_rollup_30m)")
        }
        if "domestic_import_wh" not in columns:
            connection.execute(
                "ALTER TABLE energy_rollup_30m ADD COLUMN domestic_import_wh REAL NOT NULL DEFAULT 0"
            )
        connection.commit()


def compact_history(now: int | None = None) -> None:
    """Roll minute Enphase samples into compact, tariff-aligned half-hour kWh.

    Half-hour usage is retained because applying Octopus Agile prices to daily
    totals would lose the time-of-use cost calculation. The existing SQLite
    cache remains the only long-term store; minute samples are short lived.
    """
    now = int(now or time.time())
    raw_cutoff = now - RAW_RETENTION_HOURS * 3600
    dt_hours = COLLECTION_INTERVAL_SECONDS / 3600.0
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM telemetry WHERE reading_time < ? ORDER BY reading_time",
            (raw_cutoff,),
        ).fetchall()
        buckets: dict[int, dict[str, float]] = {}
        for row in rows:
            timestamp = int(row["reading_time"])
            bucket = timestamp - timestamp % 1800
            totals = buckets.setdefault(
                bucket,
                {
                    "count": 0,
                    "production": 0,
                    "consumption": 0,
                    "grid_import": 0,
                    "domestic_import": 0,
                    "grid_export": 0,
                    "battery_charge": 0,
                    "battery_discharge": 0,
                },
            )
            grid_import_w = max(0.0, float(row["grid_import_w"] or 0.0))
            battery_power_w = float(row["battery_power_w"] or 0.0)
            battery_charge_w = max(0.0, -battery_power_w)
            totals["count"] += 1
            totals["production"] += float(row["production_w"] or 0.0) * dt_hours
            totals["consumption"] += float(row["consumption_w"] or 0.0) * dt_hours
            totals["grid_import"] += grid_import_w * dt_hours
            totals["domestic_import"] += max(0.0, grid_import_w - battery_charge_w) * dt_hours
            totals["grid_export"] += float(row["grid_export_w"] or 0.0) * dt_hours
            totals["battery_charge"] += battery_charge_w * dt_hours
            totals["battery_discharge"] += max(0.0, battery_power_w) * dt_hours

        for bucket, values in buckets.items():
            connection.execute(
                """
                INSERT INTO energy_rollup_30m (
                    bucket_start, sample_count, production_wh, consumption_wh,
                    grid_import_wh, grid_export_wh, battery_charge_wh,
                    battery_discharge_wh, domestic_import_wh
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bucket_start) DO UPDATE SET
                    sample_count=energy_rollup_30m.sample_count+excluded.sample_count,
                    production_wh=energy_rollup_30m.production_wh+excluded.production_wh,
                    consumption_wh=energy_rollup_30m.consumption_wh+excluded.consumption_wh,
                    grid_import_wh=energy_rollup_30m.grid_import_wh+excluded.grid_import_wh,
                    grid_export_wh=energy_rollup_30m.grid_export_wh+excluded.grid_export_wh,
                    battery_charge_wh=energy_rollup_30m.battery_charge_wh+excluded.battery_charge_wh,
                    battery_discharge_wh=energy_rollup_30m.battery_discharge_wh+excluded.battery_discharge_wh,
                    domestic_import_wh=energy_rollup_30m.domestic_import_wh+excluded.domestic_import_wh
                """,
                (
                    bucket,
                    int(values["count"]),
                    values["production"],
                    values["consumption"],
                    values["grid_import"],
                    values["grid_export"],
                    values["battery_charge"],
                    values["battery_discharge"],
                    values["domestic_import"],
                ),
            )
        connection.execute("DELETE FROM telemetry WHERE reading_time < ?", (raw_cutoff,))
        connection.commit()


def insert_telemetry(telemetry: dict[str, Any]) -> None:
    battery = telemetry.get("battery") or {}
    with closing(connect()) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO telemetry (
                reading_time, production_w, consumption_w, grid_w, grid_import_w,
                grid_export_w, battery_soc_percent, battery_power_w, source,
                provider, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(telemetry["reading_time"]),
                float(telemetry["production_w"]),
                telemetry.get("consumption_w"),
                telemetry.get("grid_w"),
                float(telemetry["grid_import_w"]),
                float(telemetry["grid_export_w"]),
                battery.get("soc_percent"),
                battery.get("power_w"),
                str(telemetry["source"]),
                str(telemetry["provider"]),
                int(time.time()),
            ),
        )
        connection.commit()
    compact_history()


def read_history(hours: int) -> list[dict[str, Any]]:
    cutoff = int(time.time()) - hours * 3600
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT reading_time, production_w, consumption_w, grid_w,
                   grid_import_w, grid_export_w, battery_soc_percent,
                   battery_power_w, source, provider
            FROM telemetry WHERE reading_time >= ? ORDER BY reading_time ASC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def read_rollups(start: int, end: int, granularity: str = "auto") -> dict[str, Any]:
    """Return Enphase-derived half-hour energy and Octopus prices/costs."""
    if end <= start:
        return {"granularity": "30m", "start": start, "end": end, "points": []}
    if granularity not in {"auto", "30m", "day"}:
        raise ValueError("granularity must be auto, 30m, or day")
    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT * FROM energy_rollup_30m
            WHERE bucket_start >= ? AND bucket_start < ?
            ORDER BY bucket_start
            """,
            (start - start % 1800, end),
        ).fetchall()

    points = []
    rolled_buckets = set()
    for row in rows:
        rolled_buckets.add(int(row["bucket_start"]))
        points.append(
            {
                "timestamp": int(row["bucket_start"]),
                "sample_count": int(row["sample_count"]),
                "production_kwh": round(float(row["production_wh"]) / 1000, 6),
                "consumption_kwh": round(float(row["consumption_wh"]) / 1000, 6),
                "grid_import_kwh": round(float(row["grid_import_wh"]) / 1000, 6),
                "domestic_import_kwh": round(float(row["domestic_import_wh"]) / 1000, 6),
                "grid_export_kwh": round(float(row["grid_export_wh"]) / 1000, 6),
                "battery_charge_kwh": round(float(row["battery_charge_wh"]) / 1000, 6),
                "battery_discharge_kwh": round(float(row["battery_discharge_wh"]) / 1000, 6),
            }
        )

    # Keep the report API's 35-day source window intact. During that window
    # samples have not yet been compacted, so construct the same half-hour
    # shape directly from the Enphase cache for long-range dashboard requests.
    with closing(connect()) as connection:
        raw_rows = connection.execute(
            """SELECT * FROM telemetry
               WHERE reading_time >= ? AND reading_time < ?
               ORDER BY reading_time""",
            (start, end),
        ).fetchall()
    raw_buckets: dict[int, dict[str, float]] = {}
    dt_hours = COLLECTION_INTERVAL_SECONDS / 3600.0
    for row in raw_rows:
        timestamp = int(row["reading_time"])
        bucket = timestamp - timestamp % 1800
        if bucket in rolled_buckets:
            continue
        values = raw_buckets.setdefault(
            bucket,
            {"count": 0, "production": 0, "consumption": 0, "grid_import": 0,
             "domestic_import": 0, "grid_export": 0, "battery_charge": 0,
             "battery_discharge": 0},
        )
        grid_import_w = max(0.0, float(row["grid_import_w"] or 0.0))
        battery_power_w = float(row["battery_power_w"] or 0.0)
        battery_charge_w = max(0.0, -battery_power_w)
        values["count"] += 1
        values["production"] += float(row["production_w"] or 0.0) * dt_hours
        values["consumption"] += float(row["consumption_w"] or 0.0) * dt_hours
        values["grid_import"] += grid_import_w * dt_hours
        values["domestic_import"] += max(0.0, grid_import_w - battery_charge_w) * dt_hours
        values["grid_export"] += float(row["grid_export_w"] or 0.0) * dt_hours
        values["battery_charge"] += battery_charge_w * dt_hours
        values["battery_discharge"] += max(0.0, battery_power_w) * dt_hours
    for bucket, values in raw_buckets.items():
        points.append(
            {
                "timestamp": bucket,
                "sample_count": int(values["count"]),
                "production_kwh": round(values["production"] / 1000, 6),
                "consumption_kwh": round(values["consumption"] / 1000, 6),
                "grid_import_kwh": round(values["grid_import"] / 1000, 6),
                "domestic_import_kwh": round(values["domestic_import"] / 1000, 6),
                "grid_export_kwh": round(values["grid_export"] / 1000, 6),
                "battery_charge_kwh": round(values["battery_charge"] / 1000, 6),
                "battery_discharge_kwh": round(values["battery_discharge"] / 1000, 6),
            }
        )
    points.sort(key=lambda point: point["timestamp"])

    timezone_name = str(load_config()["site"]["timezone"])
    if points:
        from app.services.octopus import account_tariffs, tariff_prices_range

        tariffs = account_tariffs()
        zone = ZoneInfo(timezone_name)
        first_day = datetime.fromtimestamp(start, zone).date()
        last_day = datetime.fromtimestamp(end - 1, zone).date()
        rates = tariff_prices_range(
            tariffs["import"]["tariff_code"], first_day, last_day, timezone_name
        )
        for point in points:
            rate = rates.get(point["timestamp"])
            point["import_p_per_kwh"] = rate
            point["import_price_available"] = rate is not None
            point["domestic_import_cost_gbp"] = (
                None
                if rate is None
                else round(point["domestic_import_kwh"] * rate / 100, 6)
            )

    zone = ZoneInfo(timezone_name)
    for point in points:
        start_at = datetime.fromtimestamp(point["timestamp"], timezone.utc)
        end_at = datetime.fromtimestamp(point["timestamp"] + 1800, timezone.utc)
        point["valid_from"] = start_at.isoformat()
        point["valid_to"] = end_at.isoformat()
        point["local_from"] = start_at.astimezone(zone).isoformat()
        point["local_to"] = end_at.astimezone(zone).isoformat()

    totals = {}
    for key in (
        "production_kwh",
        "consumption_kwh",
        "grid_import_kwh",
        "domestic_import_kwh",
        "grid_export_kwh",
    ):
        totals[key] = round(sum(point[key] for point in points), 6)
    totals["domestic_import_cost_gbp"] = (
        None
        if not points or any(point.get("domestic_import_cost_gbp") is None for point in points)
        else round(sum(point["domestic_import_cost_gbp"] for point in points), 6)
    )
    expected_count = max(0, (end - start + 1799) // 1800)
    coverage_percent = round(100 * len(points) / expected_count, 1) if expected_count else 100.0
    return {
        "granularity": "30m",
        "complete": bool(points) and coverage_percent >= 99.0,
        "coverage_percent": coverage_percent,
        "timezone": timezone_name,
        "start": start,
        "end": end,
        "count": len(points),
        "totals": totals,
        "points": points,
    }


def history_summary(hours: int) -> dict[str, Any]:
    points = read_history(hours)
    if not points:
        return {
            "hours": hours,
            "count": 0,
            "first_reading_time": None,
            "last_reading_time": None,
            "points": [],
        }
    return {
        "hours": hours,
        "count": len(points),
        "first_reading_time": points[0]["reading_time"],
        "last_reading_time": points[-1]["reading_time"],
        "points": points,
    }


async def collect_once() -> dict[str, Any]:
    telemetry = await _client.live(force=True)
    await asyncio.to_thread(insert_telemetry, telemetry)
    return telemetry


async def collector_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await collect_once()
        except (EnphaseAuthenticationError, EnphaseUnavailableError):
            pass
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=COLLECTION_INTERVAL_SECONDS)
        except TimeoutError:
            continue


async def start_history_collector() -> None:
    global _collector_task, _stop_event
    initialise_database()
    if _collector_task is not None and not _collector_task.done():
        return
    _stop_event = asyncio.Event()
    _collector_task = asyncio.create_task(
        collector_loop(_stop_event), name="lifeos-energy-history-collector"
    )


async def stop_history_collector() -> None:
    global _collector_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _collector_task is not None:
        try:
            await asyncio.wait_for(_collector_task, timeout=10)
        except TimeoutError:
            _collector_task.cancel()
    _collector_task = None
    _stop_event = None
