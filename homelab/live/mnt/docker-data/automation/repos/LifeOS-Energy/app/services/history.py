
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from typing import Any

from app.config import load_config
from app.services.octopus import OctopusError, account_tariffs, tariff_prices
from zoneinfo import ZoneInfo

from app.services.enphase import (
    EnphaseAuthenticationError,
    EnphaseClient,
    EnphaseUnavailableError,
)


DATABASE_PATH = Path(
    os.getenv(
        "ENERGY_HISTORY_DATABASE",
        "/data/lifeos-energy-history.sqlite3",
    )
)

COLLECTION_INTERVAL_SECONDS = max(
    30,
    int(os.getenv("ENERGY_COLLECTION_INTERVAL_SECONDS", "60")),
)
RAW_RETENTION_HOURS = max(48, int(os.getenv("ENERGY_RAW_RETENTION_HOURS", "48")))
HALF_HOUR_RETENTION_DAYS = max(30, int(os.getenv("ENERGY_HALF_HOUR_RETENTION_DAYS", "90")))

_client = EnphaseClient()
_collector_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=10,
    )
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
            """
            CREATE INDEX IF NOT EXISTS
            idx_telemetry_recorded_at
            ON telemetry(recorded_at)
            """
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
                battery_discharge_wh REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS energy_rollup_daily (
                day_start INTEGER PRIMARY KEY,
                sample_count INTEGER NOT NULL,
                production_wh REAL NOT NULL,
                consumption_wh REAL NOT NULL,
                grid_import_wh REAL NOT NULL,
                grid_export_wh REAL NOT NULL,
                battery_charge_wh REAL NOT NULL,
                battery_discharge_wh REAL NOT NULL
            )
            """
        )
        connection.commit()


def compact_history(now: int | None = None) -> None:
    """Downsample telemetry so raw minute data is short lived.

    Raw telemetry is kept for 48h (configurable). Before deletion it is folded
    into 30-minute energy buckets. 30-minute buckets older than 90d
    (configurable) are folded into permanent daily summaries.
    """
    now = int(now or time.time())
    raw_cutoff = now - RAW_RETENTION_HOURS * 3600
    half_hour_cutoff = now - HALF_HOUR_RETENTION_DAYS * 86400
    with closing(connect()) as connection:
        rows = connection.execute(
            """SELECT * FROM telemetry WHERE reading_time < ? ORDER BY reading_time""",
            (raw_cutoff,),
        ).fetchall()
        buckets: dict[int, dict[str, float]] = {}
        for row in rows:
            t=int(row["reading_time"]); bucket=t-(t%1800)
            b=buckets.setdefault(bucket,{"n":0.0,"production":0.0,"consumption":0.0,"import":0.0,"export":0.0,"charge":0.0,"discharge":0.0})
            dt=float(COLLECTION_INTERVAL_SECONDS)/3600.0
            bp=float(row["battery_power_w"] or 0.0)
            b["n"]+=1;b["production"]+=float(row["production_w"] or 0)*dt
            b["consumption"]+=float(row["consumption_w"] or 0)*dt;b["import"]+=float(row["grid_import_w"] or 0)*dt
            b["export"]+=float(row["grid_export_w"] or 0)*dt;b["charge"]+=max(0.0,-bp)*dt;b["discharge"]+=max(0.0,bp)*dt
        for bucket,b in buckets.items():
            connection.execute(
                """INSERT INTO energy_rollup_30m
                   (bucket_start,sample_count,production_wh,consumption_wh,grid_import_wh,grid_export_wh,battery_charge_wh,battery_discharge_wh)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(bucket_start) DO UPDATE SET
                     sample_count=energy_rollup_30m.sample_count+excluded.sample_count,
                     production_wh=energy_rollup_30m.production_wh+excluded.production_wh,
                     consumption_wh=energy_rollup_30m.consumption_wh+excluded.consumption_wh,
                     grid_import_wh=energy_rollup_30m.grid_import_wh+excluded.grid_import_wh,
                     grid_export_wh=energy_rollup_30m.grid_export_wh+excluded.grid_export_wh,
                     battery_charge_wh=energy_rollup_30m.battery_charge_wh+excluded.battery_charge_wh,
                     battery_discharge_wh=energy_rollup_30m.battery_discharge_wh+excluded.battery_discharge_wh""",
                (bucket,int(b["n"]),b["production"],b["consumption"],b["import"],b["export"],b["charge"],b["discharge"]))
        connection.execute("DELETE FROM telemetry WHERE reading_time < ?",(raw_cutoff,))

        old=connection.execute("SELECT * FROM energy_rollup_30m WHERE bucket_start < ? ORDER BY bucket_start",(half_hour_cutoff,)).fetchall()
        days: dict[int, dict[str, float]]={}
        for row in old:
            d=datetime.fromtimestamp(int(row["bucket_start"]),timezone.utc)
            day=int(datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp())
            b=days.setdefault(day,{"n":0.0,"production":0.0,"consumption":0.0,"import":0.0,"export":0.0,"charge":0.0,"discharge":0.0})
            b["n"]+=int(row["sample_count"])
            for src,dst in (("production_wh","production"),("consumption_wh","consumption"),("grid_import_wh","import"),("grid_export_wh","export"),("battery_charge_wh","charge"),("battery_discharge_wh","discharge")): b[dst]+=float(row[src])
        for day,b in days.items():
            connection.execute(
                """INSERT INTO energy_rollup_daily
                   (day_start,sample_count,production_wh,consumption_wh,grid_import_wh,grid_export_wh,battery_charge_wh,battery_discharge_wh)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(day_start) DO UPDATE SET
                     sample_count=energy_rollup_daily.sample_count+excluded.sample_count,
                     production_wh=energy_rollup_daily.production_wh+excluded.production_wh,
                     consumption_wh=energy_rollup_daily.consumption_wh+excluded.consumption_wh,
                     grid_import_wh=energy_rollup_daily.grid_import_wh+excluded.grid_import_wh,
                     grid_export_wh=energy_rollup_daily.grid_export_wh+excluded.grid_export_wh,
                     battery_charge_wh=energy_rollup_daily.battery_charge_wh+excluded.battery_charge_wh,
                     battery_discharge_wh=energy_rollup_daily.battery_discharge_wh+excluded.battery_discharge_wh""",
                (day,int(b["n"]),b["production"],b["consumption"],b["import"],b["export"],b["charge"],b["discharge"]))
        connection.execute("DELETE FROM energy_rollup_30m WHERE bucket_start < ?",(half_hour_cutoff,))
        connection.commit()


def insert_telemetry(telemetry: dict[str, Any]) -> None:
    battery = telemetry.get("battery") or {}

    with closing(connect()) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO telemetry (
                reading_time,
                production_w,
                consumption_w,
                grid_w,
                grid_import_w,
                grid_export_w,
                battery_soc_percent,
                battery_power_w,
                source,
                provider,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            SELECT
                reading_time,
                production_w,
                consumption_w,
                grid_w,
                grid_import_w,
                grid_export_w,
                battery_soc_percent,
                battery_power_w,
                source,
                provider
            FROM telemetry
            WHERE reading_time >= ?
            ORDER BY reading_time ASC
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]



def read_rollups(start: int, end: int, granularity: str = "auto") -> dict[str, Any]:
    """Return compact energy history for an arbitrary epoch range."""
    if end <= start:
        return {"granularity": granularity, "points": []}
    span = end - start
    if granularity == "auto":
        granularity = "30m" if span <= HALF_HOUR_RETENTION_DAYS * 86400 else "day"
    table = "energy_rollup_30m" if granularity == "30m" else "energy_rollup_daily"
    stamp = "bucket_start" if granularity == "30m" else "day_start"
    with closing(connect()) as connection:
        rows = connection.execute(
            f"""SELECT * FROM {table} WHERE {stamp} >= ? AND {stamp} < ? ORDER BY {stamp}""",
            (start, end),
        ).fetchall()
    points = []
    for row in rows:
        points.append({
            "timestamp": int(row[stamp]),
            "sample_count": int(row["sample_count"]),
            "production_kwh": round(float(row["production_wh"]) / 1000.0, 6),
            "consumption_kwh": round(float(row["consumption_wh"]) / 1000.0, 6),
            "grid_import_kwh": round(float(row["grid_import_wh"]) / 1000.0, 6),
            "grid_export_kwh": round(float(row["grid_export_wh"]) / 1000.0, 6),
            "battery_charge_kwh": round(float(row["battery_charge_wh"]) / 1000.0, 6),
            "battery_discharge_kwh": round(float(row["battery_discharge_wh"]) / 1000.0, 6),
        })
    # Prices are authoritative Octopus data and are joined on read rather than
    # duplicated in the local history database.
    try:
        config = load_config()
        zone = str(config["site"]["timezone"])
        tariffs = account_tariffs()
        rates = {}
        local_day = datetime.fromtimestamp(start, ZoneInfo(zone)).date()
        final_day = datetime.fromtimestamp(end, ZoneInfo(zone)).date()
        while local_day <= final_day:
            try:
                day_prices = tariff_prices(tariffs["import"]["tariff_code"], local_day, zone)
                for slot in day_prices["slots"]:
                    rates[int(datetime.fromisoformat(slot["valid_from"]).timestamp())] = slot.get("rate_p_per_kwh")
            except OctopusError:
                pass
            local_day = local_day.fromordinal(local_day.toordinal() + 1)
        if granularity == "30m":
            for point in points:
                rate = rates.get(int(point["timestamp"]))
                point["import_p_per_kwh"] = rate
                point["import_price_available"] = rate is not None
                point["domestic_import_cost_gbp"] = None if rate is None else round(point["grid_import_kwh"] * float(rate) / 100.0, 6)
    except OctopusError:
        pass
    return {"granularity": granularity, "start": start, "end": end, "points": points}


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
        except (
            EnphaseAuthenticationError,
            EnphaseUnavailableError,
        ):
            pass
        except Exception:
            pass

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=COLLECTION_INTERVAL_SECONDS,
            )
        except TimeoutError:
            continue


async def start_history_collector() -> None:
    global _collector_task, _stop_event

    initialise_database()

    if _collector_task is not None and not _collector_task.done():
        return

    _stop_event = asyncio.Event()
    _collector_task = asyncio.create_task(
        collector_loop(_stop_event),
        name="lifeos-energy-history-collector",
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
