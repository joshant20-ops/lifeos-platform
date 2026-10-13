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


def _power_values(row: Any) -> dict[str, float]:
    grid_import_w = max(0.0, float(row["grid_import_w"] or 0.0))
    grid_export_w = max(0.0, float(row["grid_export_w"] or 0.0))
    battery_power_w = float(row["battery_power_w"] or 0.0)
    battery_charge_w = max(0.0, -battery_power_w)
    return {
        "production": max(0.0, float(row["production_w"] or 0.0)),
        "consumption": max(0.0, float(row["consumption_w"] or 0.0)),
        "grid_import": grid_import_w,
        "domestic_import": max(0.0, grid_import_w - battery_charge_w),
        "grid_export": grid_export_w,
        "battery_charge": battery_charge_w,
        "battery_discharge": max(0.0, battery_power_w),
    }


def _accumulate_sample_interval(
    buckets: dict[int, dict[str, float]],
    left: Any,
    right: Any,
    *,
    clip_start: float,
    clip_end: float,
) -> None:
    """Integrate Enphase power between two timestamped samples into 30m buckets."""
    left_time = float(left["reading_time"])
    right_time = float(right["reading_time"])
    if right_time <= left_time:
        return
    start = max(left_time, clip_start)
    end = min(right_time, clip_end)
    if end <= start:
        return
    left_values = _power_values(left)
    right_values = _power_values(right)
    while start < end:
        bucket = int(start) - int(start) % 1800
        segment_end = min(end, bucket + 1800)
        span = right_time - left_time
        start_ratio = (start - left_time) / span
        end_ratio = (segment_end - left_time) / span
        totals = buckets.setdefault(
            bucket,
            {
                "count": 0,
                "production": 0.0,
                "consumption": 0.0,
                "grid_import": 0.0,
                "domestic_import": 0.0,
                "grid_export": 0.0,
                "battery_charge": 0.0,
                "battery_discharge": 0.0,
            },
        )
        duration_hours = (segment_end - start) / 3600.0
        for key in left_values:
            start_w = left_values[key] + (right_values[key] - left_values[key]) * start_ratio
            end_w = left_values[key] + (right_values[key] - left_values[key]) * end_ratio
            totals[key] += (start_w + end_w) * 0.5 * duration_hours
        start = segment_end


def compact_history(now: int | None = None) -> None:
    """Compact completed Enphase sample intervals into tariff-aligned half-hour kWh.

    Each sample interval is integrated once using its actual timestamps and
    linearly interpolated power, matching the existing interval-report method.
    """
    now = int(now or time.time())
    raw_cutoff = now - RAW_RETENTION_HOURS * 3600
    with closing(connect()) as connection:
        old_rows = connection.execute(
            "SELECT * FROM telemetry WHERE reading_time < ? ORDER BY reading_time",
            (raw_cutoff,),
        ).fetchall()
        if not old_rows:
            return
        next_row = connection.execute(
            "SELECT * FROM telemetry WHERE reading_time >= ? ORDER BY reading_time LIMIT 1",
            (raw_cutoff,),
        ).fetchone()
        rows = list(old_rows)
        if next_row is not None:
            rows.append(next_row)
            process_rows = old_rows
        else:
            # Keep the last unclosed sample until a later reading can bound it.
            process_rows = old_rows[:-1]
            if not process_rows:
                return
        if not process_rows:
            return

        buckets: dict[int, dict[str, float]] = {}
        for row in process_rows:
            bucket = int(row["reading_time"]) - int(row["reading_time"]) % 1800
            buckets.setdefault(
                bucket,
                {
                    "count": 0,
                    "production": 0.0,
                    "consumption": 0.0,
                    "grid_import": 0.0,
                    "domestic_import": 0.0,
                    "grid_export": 0.0,
                    "battery_charge": 0.0,
                    "battery_discharge": 0.0,
                },
            )["count"] += 1

        for left, right in zip(rows, rows[1:]):
            if int(left["reading_time"]) >= raw_cutoff:
                continue
            _accumulate_sample_interval(
                buckets, left, right, clip_start=float("-inf"), clip_end=float("inf")
            )

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
        processed_end = int(process_rows[-1]["reading_time"]) + 1
        connection.execute(
            "DELETE FROM telemetry WHERE reading_time < ?", (processed_end,)
        )
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
    """Return Enphase-derived half-hour energy joined to Octopus prices."""
    if end <= start:
        return {
            "granularity": "30m", "start": start, "end": end,
            "timezone": str(load_config()["site"]["timezone"]), "points": [],
            "count": 0, "coverage_percent": 0.0, "complete": False,
        }
    if granularity not in {"auto", "30m"}:
        raise ValueError("granularity must be auto or 30m")
    with closing(connect()) as connection:
        rows = connection.execute(
            """SELECT * FROM energy_rollup_30m
               WHERE bucket_start >= ? AND bucket_start < ?
               ORDER BY bucket_start""",
            (start - start % 1800, end),
        ).fetchall()

    points: list[dict[str, Any]] = []
    by_bucket: dict[int, dict[str, Any]] = {}
    energy_fields = (
        "production_kwh", "consumption_kwh", "grid_import_kwh",
        "domestic_import_kwh", "grid_export_kwh", "battery_charge_kwh",
        "battery_discharge_kwh",
    )
    for row in rows:
        point = {
            "timestamp": int(row["bucket_start"]),
            "sample_count": int(row["sample_count"]),
            "production_kwh": float(row["production_wh"]) / 1000,
            "consumption_kwh": float(row["consumption_wh"]) / 1000,
            "grid_import_kwh": float(row["grid_import_wh"]) / 1000,
            "domestic_import_kwh": float(row["domestic_import_wh"]) / 1000,
            "grid_export_kwh": float(row["grid_export_wh"]) / 1000,
            "battery_charge_kwh": float(row["battery_charge_wh"]) / 1000,
            "battery_discharge_kwh": float(row["battery_discharge_wh"]) / 1000,
        }
        points.append(point)
        by_bucket[point["timestamp"]] = point

    # Integrate recent Enphase sample intervals by actual timestamps. Include
    # one sample before the requested window and one after it to close the
    # boundary intervals, but never re-integrate samples already compacted.
    raw_cutoff = int(time.time()) - RAW_RETENTION_HOURS * 3600
    raw_start = max(start, raw_cutoff)
    with closing(connect()) as connection:
        before = connection.execute(
            "SELECT * FROM telemetry WHERE reading_time < ? ORDER BY reading_time DESC LIMIT 1",
            (raw_start,),
        ).fetchone()
        recent = connection.execute(
            "SELECT * FROM telemetry WHERE reading_time >= ? AND reading_time < ? ORDER BY reading_time",
            (raw_start, end),
        ).fetchall()
        after = connection.execute(
            "SELECT * FROM telemetry WHERE reading_time >= ? ORDER BY reading_time LIMIT 1",
            (end,),
        ).fetchone()
    raw_rows = list(recent)
    if before is not None:
        raw_rows.insert(0, before)
    if after is not None:
        raw_rows.append(after)

    raw_buckets: dict[int, dict[str, float]] = {}
    for row in recent:
        timestamp = int(row["reading_time"])
        bucket = timestamp - timestamp % 1800
        values = raw_buckets.setdefault(
            bucket,
            {
                "count": 0,
                "production": 0.0,
                "consumption": 0.0,
                "grid_import": 0.0,
                "domestic_import": 0.0,
                "grid_export": 0.0,
                "battery_charge": 0.0,
                "battery_discharge": 0.0,
            },
        )
        values["count"] += 1

    for left, right in zip(raw_rows, raw_rows[1:]):
        if int(left["reading_time"]) < raw_cutoff:
            continue
        _accumulate_sample_interval(
            raw_buckets,
            left,
            right,
            clip_start=float(start),
            clip_end=float(end),
        )

    for bucket, values in raw_buckets.items():
        point = by_bucket.get(bucket)
        if point is None:
            point = {
                "timestamp": bucket,
                "sample_count": 0,
                **{field: 0.0 for field in energy_fields},
            }
            points.append(point)
            by_bucket[bucket] = point
        point["sample_count"] += int(values["count"])
        for field, source in (
            ("production_kwh", "production"),
            ("consumption_kwh", "consumption"),
            ("grid_import_kwh", "grid_import"),
            ("domestic_import_kwh", "domestic_import"),
            ("grid_export_kwh", "grid_export"),
            ("battery_charge_kwh", "battery_charge"),
            ("battery_discharge_kwh", "battery_discharge"),
        ):
            point[field] += values[source] / 1000

    points.sort(key=lambda point: point["timestamp"])
    timezone_name = str(load_config()["site"]["timezone"])
    rates: dict[int, float] = {}
    price_error = False
    if points:
        from app.services.octopus import OctopusError, account_tariffs, tariff_prices_range

        try:
            tariffs = account_tariffs()
            zone = ZoneInfo(timezone_name)
            first_day = datetime.fromtimestamp(start, zone).date()
            last_day = datetime.fromtimestamp(end - 1, zone).date()
            rates = tariff_prices_range(
                tariffs["import"]["tariff_code"], first_day, last_day, timezone_name
            )
        except OctopusError:
            price_error = True
        for point in points:
            rate = rates.get(point["timestamp"])
            point["import_p_per_kwh"] = rate
            point["import_price_available"] = rate is not None
            point["domestic_import_cost_gbp"] = (
                None if rate is None
                else round(point["domestic_import_kwh"] * rate / 100, 6)
            )

    zone = ZoneInfo(timezone_name)
    for point in points:
        sample_capacity = max(1, 1800 // COLLECTION_INTERVAL_SECONDS)
        point["sample_coverage_percent"] = round(
            min(100.0, point["sample_count"] * 100 / sample_capacity), 1
        )
        start_at = datetime.fromtimestamp(point["timestamp"], timezone.utc)
        end_at = datetime.fromtimestamp(point["timestamp"] + 1800, timezone.utc)
        point["valid_from"] = start_at.isoformat()
        point["valid_to"] = end_at.isoformat()
        point["local_from"] = start_at.astimezone(zone).isoformat()
        point["local_to"] = end_at.astimezone(zone).isoformat()
        for field in energy_fields:
            point[field] = round(point[field], 6)

    totals = {
        field: round(sum(point[field] for point in points), 6)
        for field in energy_fields
    }
    totals["domestic_import_cost_gbp"] = (
        None if not points or any(point.get("domestic_import_cost_gbp") is None for point in points)
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
        "price_source_available": bool(points) and not price_error and all(
            point["import_price_available"] for point in points
        ),
        "missing_price_slots": sum(1 for point in points if not point["import_price_available"]),
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
